"""Streamable HTTP transport for the wingman-mcp server.

Wraps the shared MCP tool app (``wingman_mcp.server.app``) with the Entra
auth middleware, the per-request credential-header middleware, and the
OAuth discovery + shim endpoints. Used for hosted/cloud deployments;
end-user credentials arrive as request headers and are never stored.
"""
import os

from wingman_mcp.server import app


def _validate_http_auth_config() -> None:
    """Refuse to start the HTTP server with no usable auth path.

    Either ENTRA_TENANT_ID (Entra JWT auth) or WINGMAN_MCP_ACCESS_KEY
    (static-key fallback) must be set; otherwise the server would be
    effectively open. Failing here is loud and at startup, not silent
    and at request time.
    """
    if not os.environ.get("ENTRA_TENANT_ID", "").strip() and not os.environ.get(
        "WINGMAN_MCP_ACCESS_KEY", ""
    ).strip():
        raise SystemExit(
            "Refusing to start HTTP server: neither ENTRA_TENANT_ID nor "
            "WINGMAN_MCP_ACCESS_KEY is set. Configure Entra ID authentication "
            "or set a static access key."
        )


async def run_http_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the MCP server over Streamable HTTP for hosted/cloud deployments.

    Each user's UEM credentials are passed via request headers and are never
    stored server-side. Identity is verified by EntraAuthMiddleware against
    a single configured Entra tenant.
    """
    _validate_http_auth_config()

    try:
        import json as _json
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
        from starlette.types import Receive, Scope, Send
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            f"HTTP mode requires additional dependencies: {exc}\n"
            "Install with: pip install 'wingman-mcp-server'"
        ) from exc

    from wingman_mcp_server.middleware import CredentialHeaderMiddleware
    from wingman_mcp_server.entra_auth import EntraAuthMiddleware
    from wingman_mcp_server.well_known import (
        PATH as WELL_KNOWN_PATH,
        build_metadata,
        resource_url_from_scope,
    )
    from wingman_mcp_server import oauth_shim

    session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=None,
        json_response=False,
        stateless=True,
    )

    tenant_id = os.environ.get("ENTRA_TENANT_ID", "").strip() or None
    app_id_uri = os.environ.get("ENTRA_APP_ID_URI", "").strip() or "api://wingman-mcp"
    audience = os.environ.get("ENTRA_AUDIENCE", "").strip() or app_id_uri
    required_scope = os.environ.get("ENTRA_REQUIRED_SCOPE", "mcp.access").strip()
    static_access_key = os.environ.get("WINGMAN_MCP_ACCESS_KEY", "").strip() or None
    public_url = os.environ.get("WINGMAN_MCP_PUBLIC_URL", "").strip() or None
    client_id = os.environ.get("ENTRA_CLIENT_ID", "").strip() or None
    shim_enabled = bool(tenant_id and client_id)

    def _public_base(asgi_scope: Scope) -> str:
        """Issuer URL for shim metadata. Mirrors resource_url_from_scope but
        without the /mcp suffix."""
        if public_url:
            return public_url.rstrip("/")
        headers = dict(asgi_scope.get("headers", []))
        proto = (
            headers.get(b"x-forwarded-proto", b"").decode("ascii", errors="replace").strip()
            or asgi_scope.get("scheme")
            or "http"
        )
        host = headers.get(b"host", b"").decode("ascii", errors="replace").strip()
        if not host:
            server = asgi_scope.get("server") or ("localhost", 0)
            host = f"{server[0]}:{server[1]}"
        return f"{proto}://{host}"

    class _App:
        """ASGI app: /health, OAuth discovery, OAuth shim endpoints, /mcp."""

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "lifespan":
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                msg = await receive()
                if msg["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                return

            if scope["type"] != "http":
                return

            path = scope["path"]
            method = scope.get("method", "GET")

            if path == "/health":
                await PlainTextResponse("ok")(scope, receive, send)
                return

            if path == WELL_KNOWN_PATH or path.startswith(WELL_KNOWN_PATH + "/"):
                if not tenant_id:
                    await JSONResponse({"error": "not_found"}, status_code=404)(
                        scope, receive, send
                    )
                    return
                metadata = build_metadata(
                    resource_url=resource_url_from_scope(
                        scope, public_url_override=public_url
                    ),
                    tenant_id=tenant_id,
                    app_id_uri=app_id_uri,
                    required_scope=required_scope or None,
                    authorization_server_url=_public_base(scope) if shim_enabled else None,
                )
                await JSONResponse(metadata)(scope, receive, send)
                return

            if path == oauth_shim.AS_METADATA_PATH:
                if not shim_enabled:
                    await JSONResponse({"error": "not_found"}, status_code=404)(
                        scope, receive, send
                    )
                    return
                scopes = []
                if required_scope:
                    if app_id_uri.startswith("api://") and not required_scope.startswith(app_id_uri):
                        scopes = [f"{app_id_uri}/{required_scope}"]
                    else:
                        scopes = [required_scope]
                await JSONResponse(
                    oauth_shim.build_as_metadata(
                        issuer_url=_public_base(scope),
                        scopes_supported=scopes,
                    )
                )(scope, receive, send)
                return

            if path == oauth_shim.REGISTER_PATH:
                if not shim_enabled or method != "POST":
                    await JSONResponse({"error": "not_found"}, status_code=404)(
                        scope, receive, send
                    )
                    return
                body = await _read_body(receive)
                try:
                    request_body = _json.loads(body) if body else {}
                except _json.JSONDecodeError:
                    request_body = {}
                await JSONResponse(
                    oauth_shim.build_register_response(
                        client_id=client_id, request_body=request_body
                    ),
                    status_code=201,
                )(scope, receive, send)
                return

            if path == oauth_shim.AUTHORIZE_PATH:
                if not shim_enabled or method != "GET":
                    await JSONResponse({"error": "not_found"}, status_code=404)(
                        scope, receive, send
                    )
                    return
                from urllib.parse import parse_qsl
                qs = scope.get("query_string", b"").decode("ascii", errors="replace")
                params = dict(parse_qsl(qs, keep_blank_values=True))
                target = oauth_shim.entra_authorize_url(
                    tenant_id=tenant_id,
                    app_id_uri=app_id_uri,
                    query_params=params,
                )
                await RedirectResponse(target, status_code=302)(scope, receive, send)
                return

            if path == oauth_shim.TOKEN_PATH:
                if not shim_enabled or method != "POST":
                    await JSONResponse({"error": "not_found"}, status_code=404)(
                        scope, receive, send
                    )
                    return
                body = await _read_body(receive)
                headers_map = dict(scope.get("headers", []))
                ct = headers_map.get(b"content-type", b"application/x-www-form-urlencoded").decode(
                    "ascii", errors="replace"
                )
                entra_resp = await oauth_shim.proxy_token_request(
                    tenant_id=tenant_id,
                    app_id_uri=app_id_uri,
                    form_body=body,
                    content_type=ct,
                )
                await Response(
                    content=entra_resp.content,
                    status_code=entra_resp.status_code,
                    media_type=entra_resp.headers.get("content-type", "application/json"),
                )(scope, receive, send)
                return

            await session_manager.handle_request(scope, receive, send)

    async def _read_body(receive: Receive) -> bytes:
        chunks: list[bytes] = []
        while True:
            msg = await receive()
            if msg["type"] != "http.request":
                continue
            chunks.append(msg.get("body", b""))
            if not msg.get("more_body", False):
                break
        return b"".join(chunks)

    inner_app = CredentialHeaderMiddleware(_App())
    asgi_app = EntraAuthMiddleware(
        inner_app,
        tenant_id=tenant_id,
        audience=audience,
        required_scope=required_scope,
        static_access_key=static_access_key,
    )

    print(f"wingman-mcp HTTP server starting on {host}:{port}")
    print(f"MCP endpoint : http://{host}:{port}/mcp")
    print(f"Health check : http://{host}:{port}/health")
    if tenant_id:
        print(f"Entra tenant : {tenant_id} (audience={audience})")
        print(f"OAuth metadata: http://{host}:{port}{WELL_KNOWN_PATH}")
    if shim_enabled:
        print(f"OAuth shim   : ENABLED (client_id={client_id})")
    if public_url:
        print(f"Public URL   : {public_url}")
    if static_access_key:
        print("Static access key fallback: ENABLED")

    config = uvicorn.Config(asgi_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    async with session_manager.run():
        await server.serve()
