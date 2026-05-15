"""ASGI middleware for HTTP server mode.

Extracts per-product API credentials from request headers and stores them
in a ContextVar so MCP tool handlers can use them without any server-side
credential storage. The header name per field is declared in each
CredentialSchema's `http_header_names`, so this code stays generic across
all supported products (UEM, Horizon, App Volumes, Access, Identity
Service, Horizon Cloud).

A product's entry is only present in the resulting bundle when ALL of
that product's fields (secret_keys + config_keys) were supplied as
headers; partially-set products are dropped so tool handlers can rely
on a fully-populated dict if they get one.

Access control is handled upstream by EntraAuthMiddleware. The auth
bypass list (health, OAuth discovery, OAuth shim) lives in well_known.
"""
from starlette.types import ASGIApp, Receive, Scope, Send

from wingman_mcp.credentials import SCHEMAS
from wingman_mcp.request_context import _is_http_request, _request_credentials
from wingman_mcp_server.well_known import is_public_path


def _collect_credentials(headers: dict[bytes, bytes]) -> dict[str, dict[str, str]]:
    """Scan headers for each product's declared field-header mapping.

    Returns a dict keyed by product slug. Only products whose required
    fields are all present in the headers are included.
    """
    bundle: dict[str, dict[str, str]] = {}
    for product, schema in SCHEMAS.items():
        if not schema.http_header_names:
            continue
        product_creds: dict[str, str] = {}
        for schema_field, header_name in schema.http_header_names.items():
            value = (
                headers.get(header_name.lower().encode(), b"")
                .decode("utf-8", errors="replace")
                .strip()
            )
            if value:
                # Trailing-slash normalisation for URL fields (matches the
                # pre-refactor UEM behaviour the API clients expect).
                if schema_field.endswith("_url"):
                    value = value.rstrip("/")
                product_creds[schema_field] = value
        required = set(schema.secret_keys) | set(schema.config_keys)
        if required.issubset(product_creds.keys()):
            bundle[product] = product_creds
    return bundle


class CredentialHeaderMiddleware:
    """Reads per-product API credentials from request headers."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if is_public_path(path):
            await self._app(scope, receive, send)
            return

        headers: dict[bytes, bytes] = dict(scope["headers"])
        bundle = _collect_credentials(headers)

        http_token = _is_http_request.set(True)
        creds_token = _request_credentials.set(bundle or None)
        try:
            await self._app(scope, receive, send)
        finally:
            _request_credentials.reset(creds_token)
            _is_http_request.reset(http_token)
