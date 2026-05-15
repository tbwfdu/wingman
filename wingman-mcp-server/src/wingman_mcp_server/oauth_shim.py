"""OAuth 2.0 shim that makes Entra ID look RFC 7591-compatible to MCP clients.

The MCP authorization spec assumes the authorization server supports OAuth
Dynamic Client Registration (RFC 7591). Entra ID doesn't: apps must be
pre-registered in the tenant. Without a shim, every end-user has to paste a
multi-hundred-character static-oauth blob into their MCP client config.

This module routes the OAuth dance through wingman-mcp so the client only
needs the server URL. We:

  1. Advertise ourselves as the authorization server in protected-resource
     metadata.
  2. Serve our own AS metadata pointing at the routes below.
  3. Answer /oauth/register with a fixed, pre-registered Entra client_id
     (operator-configured via ENTRA_CLIENT_ID).
  4. Redirect /oauth/authorize to the real Entra v2 authorize endpoint with
     `offline_access` appended so refresh tokens are issued.
  5. Proxy /oauth/token POSTs to the real Entra v2 token endpoint.

The shim is stateless: PKCE is verified end-to-end by Entra, tokens are
minted by Entra against the resource audience advertised in our protected-
resource metadata, and our existing EntraAuthMiddleware validates them
unchanged.
"""
from __future__ import annotations

import time
from typing import Any, Optional
from urllib.parse import urlencode

import httpx


AS_METADATA_PATH = "/.well-known/oauth-authorization-server"
REGISTER_PATH = "/oauth/register"
AUTHORIZE_PATH = "/oauth/authorize"
TOKEN_PATH = "/oauth/token"


def _entra_base(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0"


def build_as_metadata(
    *,
    issuer_url: str,
    scopes_supported: list[str],
) -> dict:
    """RFC 8414 authorization server metadata for our shim.

    `issuer_url` is the public URL of the wingman-mcp server (no trailing
    slash). Endpoints are absolute URLs under that host.
    """
    base = issuer_url.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}{AUTHORIZE_PATH}",
        "token_endpoint": f"{base}{TOKEN_PATH}",
        "registration_endpoint": f"{base}{REGISTER_PATH}",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": scopes_supported,
    }


def build_register_response(
    *,
    client_id: str,
    request_body: dict[str, Any],
) -> dict:
    """RFC 7591 client information response.

    We don't actually register anything; we always hand back the pre-
    registered Entra client_id. The response echoes the caller's metadata
    so RFC 7591-compliant clients see a consistent picture.
    """
    response: dict[str, Any] = {
        "client_id": client_id,
        "client_id_issued_at": int(time.time()),
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
    redirect_uris = request_body.get("redirect_uris")
    if isinstance(redirect_uris, list):
        response["redirect_uris"] = redirect_uris
    client_name = request_body.get("client_name")
    if isinstance(client_name, str):
        response["client_name"] = client_name
    return response


_SPECIAL_SCOPES = frozenset({"offline_access", "openid", "profile", "email"})


def _qualify_scopes(scope_value: str, app_id_uri: Optional[str]) -> list[str]:
    """Prepend `app_id_uri` to any unqualified scope parts.

    Entra v2 wants resource-qualified scopes (``api://x/scope``). MCP
    clients vary in what they send:

    - mcp-remote sends the fully-qualified form straight from
      ``scopes_supported`` — passes through unchanged.
    - Claude Desktop sends just the scope name (``mcp.access``) plus an
      RFC 8707 ``resource`` parameter pointing at the MCP server URL
      (``https://wingman.example.com/mcp``). The URL is *not* an Entra
      resource principal, so we can't trust it as a qualification prefix
      (AADSTS500011). Use the configured App ID URI instead.

    Already-qualified parts (containing ``/`` or starting with ``api://``)
    and special OIDC scopes (``offline_access``, ``openid``, ``profile``,
    ``email``) pass through untouched.
    """
    parts = scope_value.split() if scope_value else []
    if not app_id_uri:
        return parts
    prefix = app_id_uri.rstrip("/")
    qualified: list[str] = []
    for part in parts:
        if part in _SPECIAL_SCOPES or "/" in part or part.startswith("api://"):
            qualified.append(part)
        else:
            qualified.append(f"{prefix}/{part}")
    return qualified


def entra_authorize_url(
    *,
    tenant_id: str,
    app_id_uri: Optional[str],
    query_params: dict[str, str],
) -> str:
    """Build the redirect target for /oauth/authorize.

    - Qualify any unqualified scope parts using `app_id_uri` (the App ID
      URI of the server app registration), regardless of what the client
      sent as `resource`.
    - Strip the ``resource`` parameter on the way out (AADSTS9010010
      otherwise; Entra v2 rejects requests that carry both ``resource`` and
      a resource-qualified scope).
    - Append ``offline_access`` if absent so the flow yields a refresh
      token.
    - PKCE and everything else pass through verbatim.
    """
    forwarded = {k: v for k, v in query_params.items() if k != "resource"}
    parts = _qualify_scopes(forwarded.get("scope", "").strip(), app_id_uri)
    if "offline_access" not in parts:
        parts.append("offline_access")
    forwarded["scope"] = " ".join(parts)
    return f"{_entra_base(tenant_id)}/authorize?{urlencode(forwarded)}"


async def proxy_token_request(
    *,
    tenant_id: str,
    app_id_uri: Optional[str],
    form_body: bytes,
    content_type: str,
    client: Optional[httpx.AsyncClient] = None,
) -> httpx.Response:
    """Forward a /oauth/token POST to Entra's v2 token endpoint.

    `form_body` is the application/x-www-form-urlencoded body from the
    inbound request. Strip the RFC 8707 `resource` field if present (same
    Entra v2 incompatibility as the authorize step); everything else
    (client_id, code, code_verifier, redirect_uri, refresh_token) passes
    through and Entra validates against its own records.
    """
    from urllib.parse import parse_qsl, urlencode as _urlencode

    if form_body:
        params = parse_qsl(form_body.decode("utf-8", errors="replace"), keep_blank_values=True)
        rebuilt: list[tuple[str, str]] = []
        for k, v in params:
            if k == "resource":
                continue
            if k == "scope" and app_id_uri:
                rebuilt.append((k, " ".join(_qualify_scopes(v, app_id_uri))))
            else:
                rebuilt.append((k, v))
        outbound_body = _urlencode(rebuilt).encode("utf-8")
    else:
        outbound_body = form_body

    headers = {"Content-Type": content_type or "application/x-www-form-urlencoded"}
    url = f"{_entra_base(tenant_id)}/token"
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        return await client.post(url, content=outbound_body, headers=headers)
    finally:
        if owns_client:
            await client.aclose()
