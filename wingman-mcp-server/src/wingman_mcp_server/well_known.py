"""RFC 9728 OAuth 2.0 Protected Resource Metadata for MCP discovery.

Lets MCP clients (e.g. mcp-remote) auto-discover the Entra authorization
server without each user pasting static OAuth config into their client.

Served unauthenticated at /.well-known/oauth-protected-resource and
returns 404 when ENTRA_TENANT_ID is unset (static-key-only mode has no
authorization server to advertise).
"""
from __future__ import annotations

from typing import Optional


PATH = "/.well-known/oauth-protected-resource"

# Paths that bypass authentication entirely. Includes /health, the RFC 9728
# discovery doc, and the OAuth shim endpoints (which serve OAuth metadata and
# proxy the dance to Entra; auth is enforced by Entra itself for those flows).
_PUBLIC_PATHS = frozenset({
    "/health",
    PATH,
    "/.well-known/oauth-authorization-server",
    "/oauth/register",
    "/oauth/authorize",
    "/oauth/token",
})


def is_public_path(path: str) -> bool:
    """True if `path` is served unauthenticated by the HTTP transport.

    The MCP authorization draft (2025-06-18) probes a per-resource variant
    ``/.well-known/oauth-protected-resource/<resource-path>`` before falling
    back to the bare URL, so the prefix form is allowed too.
    """
    if path in _PUBLIC_PATHS:
        return True
    if path.startswith(PATH + "/"):
        return True
    return False


def build_metadata(
    *,
    resource_url: str,
    tenant_id: str,
    app_id_uri: str,
    required_scope: Optional[str],
    authorization_server_url: Optional[str] = None,
) -> dict:
    """Build the RFC 9728 metadata document for the Entra-backed resource.

    `scopes_supported` is the fully-qualified scope value clients should
    request (e.g. ``api://wingman-mcp/mcp.access``). If `required_scope` is
    already qualified, it is used as-is. ``app_id_uri`` is the App ID URI
    on the server app registration (typically ``api://wingman-mcp``); it's
    distinct from the JWT validation audience (which may be a GUID on
    tenants where Entra v2 emits GUID-style audiences despite
    ``requestedAccessTokenVersion: 2``).

    When `authorization_server_url` is set (DCR shim active),
    ``authorization_servers`` advertises that URL instead of the Entra
    issuer. Clients then auto-discover our AS metadata and route through
    the shim, avoiding RFC 7591 incompatibility with Entra.
    """
    scopes: list[str] = []
    if required_scope:
        if app_id_uri.startswith("api://") and not required_scope.startswith(app_id_uri):
            scopes.append(f"{app_id_uri}/{required_scope}")
        else:
            scopes.append(required_scope)
    if authorization_server_url:
        as_url = authorization_server_url.rstrip("/")
    else:
        as_url = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    return {
        "resource": resource_url,
        "authorization_servers": [as_url],
        "scopes_supported": scopes,
        "bearer_methods_supported": ["header"],
    }


def resource_url_from_scope(
    scope: dict,
    *,
    public_url_override: Optional[str],
) -> str:
    """Resolve the canonical resource URL for the discovery document.

    Prefer ``WINGMAN_MCP_PUBLIC_URL`` when set so the value is stable
    regardless of how the request arrived. Otherwise derive it from
    ``x-forwarded-proto`` + ``Host`` (Azure Container Apps ingress sets
    both correctly).
    """
    if public_url_override:
        return public_url_override.rstrip("/") + "/mcp"
    headers = dict(scope.get("headers", []))
    proto = (
        headers.get(b"x-forwarded-proto", b"").decode("ascii", errors="replace").strip()
        or scope.get("scheme")
        or "http"
    )
    host = headers.get(b"host", b"").decode("ascii", errors="replace").strip()
    if not host:
        server = scope.get("server") or ("localhost", 0)
        host = f"{server[0]}:{server[1]}"
    return f"{proto}://{host}/mcp"
