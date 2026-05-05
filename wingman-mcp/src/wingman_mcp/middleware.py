"""ASGI middleware for HTTP server mode.

Extracts UEM credentials from request headers and stores them in
ContextVars so that MCP tool handlers can use them without any
server-side credential storage.

Headers consumed:
  X-UEM-Client-ID      OAuth client ID
  X-UEM-Client-Secret  OAuth client secret
  X-UEM-Token-URL      Token endpoint URL
  X-UEM-API-URL        UEM API base URL

Optional server access control:
  X-Wingman-Access-Key  Must match the WINGMAN_MCP_ACCESS_KEY env var
                        (if that var is not set, no access control is applied)
"""
import hmac
import os
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from wingman_mcp.request_context import _is_http_request, _request_credentials

_ACCESS_KEY_ENV = "WINGMAN_MCP_ACCESS_KEY"


class CredentialHeaderMiddleware:
    """Starlette-compatible ASGI middleware that reads UEM credentials from headers."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._access_key = os.environ.get(_ACCESS_KEY_ENV, "").strip()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers: dict[bytes, bytes] = dict(scope["headers"])
        path: str = scope.get("path", "")

        # Health check bypasses all auth and credential extraction.
        if path == "/health":
            await self._app(scope, receive, send)
            return

        # Optional shared access key check.
        if self._access_key:
            provided = headers.get(b"x-wingman-access-key", b"").decode("utf-8", errors="replace")
            if not hmac.compare_digest(provided, self._access_key):
                resp = JSONResponse({"error": "Unauthorized: missing or invalid X-Wingman-Access-Key"}, status_code=401)
                await resp(scope, receive, send)
                return

        # Extract UEM credential headers.
        client_id = headers.get(b"x-uem-client-id", b"").decode("utf-8", errors="replace").strip()
        client_secret = headers.get(b"x-uem-client-secret", b"").decode("utf-8", errors="replace").strip()
        token_url = headers.get(b"x-uem-token-url", b"").decode("utf-8", errors="replace").strip()
        api_base_url = headers.get(b"x-uem-api-url", b"").decode("utf-8", errors="replace").strip()

        creds = None
        if client_id and client_secret and token_url and api_base_url:
            from wingman_mcp.credentials import UEMCredentials
            creds = UEMCredentials(
                client_id=client_id,
                client_secret=client_secret,
                token_url=token_url,
                api_base_url=api_base_url.rstrip("/"),
            )

        # Set ContextVars for this request's async chain.
        http_token = _is_http_request.set(True)
        creds_token = _request_credentials.set(creds)
        try:
            await self._app(scope, receive, send)
        finally:
            _is_http_request.reset(http_token)
            _request_credentials.reset(creds_token)
