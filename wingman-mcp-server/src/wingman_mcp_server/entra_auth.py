"""Entra ID JWT authentication middleware for the HTTP transport.

Sits in front of CredentialHeaderMiddleware. Validates `Authorization: Bearer`
tokens against a single configured Entra tenant. If a static access key is
configured AND no Authorization header was sent, falls back to the legacy
X-Wingman-Access-Key header. On success, stamps a Principal into the
_request_principal ContextVar.

See docs/superpowers/specs/2026-05-14-entra-id-auth-design.md.
"""
from __future__ import annotations

import hmac
import logging
from typing import Optional

import jwt
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from wingman_mcp_server.jwks import JWKSCache, JWKSUnavailable
from wingman_mcp.request_context import (
    Principal,
    _is_http_request,
    _request_principal,
)
from wingman_mcp_server.well_known import is_public_path


log = logging.getLogger(__name__)

_REALM = 'Bearer realm="wingman-mcp"'


def _err(
    status: int,
    code: str,
    description: str,
    *,
    www_authenticate: Optional[str] = None,
):
    headers = {}
    if www_authenticate is not None:
        headers["WWW-Authenticate"] = www_authenticate
    return JSONResponse(
        {"error": code, "error_description": description},
        status_code=status,
        headers=headers,
    )


class EntraAuthMiddleware:
    """ASGI middleware that authenticates requests with Entra ID JWTs."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        tenant_id: Optional[str],
        audience: str = "api://wingman-mcp",
        required_scope: str = "mcp.access",
        static_access_key: Optional[str] = None,
        jwks_cache: Optional[JWKSCache] = None,
        clock_skew_seconds: int = 30,
    ) -> None:
        self._app = app
        self._tenant_id = tenant_id
        self._audience = audience
        self._required_scope = required_scope or ""
        self._static_access_key = static_access_key or None
        self._leeway = clock_skew_seconds
        if tenant_id:
            self._issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
            self._jwks = jwks_cache or JWKSCache(
                f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
            )
        else:
            self._issuer = None
            self._jwks = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if is_public_path(path):
            await self._app(scope, receive, send)
            return

        headers: dict[bytes, bytes] = dict(scope["headers"])
        authz = headers.get(b"authorization", b"").decode("utf-8", errors="replace").strip()

        principal: Optional[Principal] = None

        if authz:
            principal_or_resp = await self._validate_bearer(authz, scope)
            if isinstance(principal_or_resp, Principal):
                principal = principal_or_resp
            else:
                await principal_or_resp(scope, receive, send)
                return
        else:
            principal_or_resp = self._validate_static_key(headers, scope)
            if isinstance(principal_or_resp, Principal):
                principal = principal_or_resp
            else:
                await principal_or_resp(scope, receive, send)
                return

        http_token = _is_http_request.set(True)
        principal_token = _request_principal.set(principal)
        try:
            await self._app(scope, receive, send)
        finally:
            _request_principal.reset(principal_token)
            _is_http_request.reset(http_token)

    async def _validate_bearer(self, authz: str, scope: Scope):
        if not authz.lower().startswith("bearer "):
            return _err(
                401,
                "invalid_request",
                "Authorization header must be 'Bearer <token>'",
                www_authenticate='Bearer error="invalid_request"',
            )
        if self._jwks is None or self._issuer is None or self._tenant_id is None:
            return _err(
                401,
                "invalid_token",
                "Bearer tokens are not accepted by this server",
                www_authenticate='Bearer error="invalid_token"',
            )

        token = authz.split(" ", 1)[1].strip()

        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception as exc:
            log.warning("auth: unparseable JWT header: %s", exc)
            return _err(
                401,
                "invalid_token",
                "Token header could not be parsed",
                www_authenticate='Bearer error="invalid_token"',
            )

        kid = unverified_header.get("kid")
        if not kid:
            log.warning("auth: token missing kid header")
            return _err(
                401,
                "invalid_token",
                "Token header is missing 'kid'",
                www_authenticate='Bearer error="invalid_token"',
            )

        try:
            key = await self._jwks.get_key(kid)
        except JWKSUnavailable as exc:
            log.error("auth: JWKS unavailable: %s", exc)
            return _err(
                503,
                "auth_unavailable",
                "Authentication keys are temporarily unavailable",
            )

        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud", "tid", "oid"]},
                leeway=self._leeway,
            )
        except jwt.PyJWTError as exc:
            # Decode without verification just to surface the actual claims
            # alongside the expected values. Signature has already been
            # checked above (we got past `key.key`), but PyJWT raises before
            # populating `claims` on aud/iss/exp mismatch. Safe for logging:
            # we still reject the token below.
            try:
                actual = jwt.decode(token, options={"verify_signature": False})
                actual_aud = actual.get("aud")
                actual_iss = actual.get("iss")
                actual_tid = actual.get("tid")
            except Exception:
                actual_aud = actual_iss = actual_tid = "<undecodable>"
            log.warning(
                "auth: token rejected (kid=%s): %s | "
                "expected aud=%s iss=%s tid=%s | "
                "actual aud=%s iss=%s tid=%s",
                kid,
                exc,
                self._audience,
                self._issuer,
                self._tenant_id,
                actual_aud,
                actual_iss,
                actual_tid,
            )
            return _err(
                401,
                "invalid_token",
                "Token failed validation",
                www_authenticate='Bearer error="invalid_token"',
            )

        if claims.get("tid") != self._tenant_id:
            log.warning(
                "auth: tid mismatch (token tid=%s expected=%s)",
                claims.get("tid"),
                self._tenant_id,
            )
            return _err(
                401,
                "invalid_token",
                "Token tenant does not match configured tenant",
                www_authenticate='Bearer error="invalid_token"',
            )

        if self._required_scope:
            scp = claims.get("scp", "") or ""
            scopes = scp.split(" ") if isinstance(scp, str) else []
            if self._required_scope not in scopes:
                log.warning(
                    "auth: missing required scope %s (got %r)",
                    self._required_scope,
                    scp,
                )
                return _err(
                    403,
                    "insufficient_scope",
                    f"Token is missing required scope '{self._required_scope}'",
                    www_authenticate=(
                        f'Bearer error="insufficient_scope", scope="{self._required_scope}"'
                    ),
                )

        return Principal(
            oid=claims.get("oid"),
            tid=claims.get("tid"),
            upn=claims.get("preferred_username") or claims.get("upn"),
            auth_method="entra",
        )

    def _validate_static_key(self, headers: dict[bytes, bytes], scope: Scope):
        if not self._static_access_key:
            return _err(
                401,
                "unauthorized",
                "Authentication required",
                www_authenticate=_REALM,
            )

        provided = headers.get(b"x-wingman-access-key", b"").decode(
            "utf-8", errors="replace"
        )
        if not hmac.compare_digest(provided, self._static_access_key):
            return _err(
                401,
                "unauthorized",
                "Authentication required",
                www_authenticate=_REALM,
            )

        return Principal(oid=None, tid=None, upn=None, auth_method="static_key")
