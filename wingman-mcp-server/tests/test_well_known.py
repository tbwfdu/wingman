"""Tests for /.well-known/oauth-protected-resource (RFC 9728) discovery."""
from __future__ import annotations

import pytest
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from wingman_mcp_server.entra_auth import EntraAuthMiddleware
from wingman_mcp_server.middleware import CredentialHeaderMiddleware
from wingman_mcp_server.well_known import (
    PATH,
    build_metadata,
    is_public_path,
    resource_url_from_scope,
)


TENANT = "00000000-0000-0000-0000-000000000001"


class _Echo:
    """Inner app that echoes the request path so bypass tests can assert reach."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await PlainTextResponse(scope.get("path", ""))(scope, receive, send)


def test_build_metadata_qualifies_relative_scope():
    md = build_metadata(
        resource_url="https://wingman.example.com/mcp",
        tenant_id=TENANT,
        app_id_uri="api://wingman-mcp",
        required_scope="mcp.access",
    )
    assert md["resource"] == "https://wingman.example.com/mcp"
    assert md["authorization_servers"] == [
        f"https://login.microsoftonline.com/{TENANT}/v2.0"
    ]
    assert md["scopes_supported"] == ["api://wingman-mcp/mcp.access"]
    assert md["bearer_methods_supported"] == ["header"]


def test_build_metadata_preserves_already_qualified_scope():
    md = build_metadata(
        resource_url="https://wingman.example.com/mcp",
        tenant_id=TENANT,
        app_id_uri="api://wingman-mcp",
        required_scope="api://wingman-mcp/mcp.access",
    )
    assert md["scopes_supported"] == ["api://wingman-mcp/mcp.access"]


def test_build_metadata_with_non_api_app_id_uri_passes_scope_through():
    """If the App ID URI isn't an api:// URI (e.g. a verified-domain
    https:// form), we can't safely auto-prefix, so the scope is advertised
    bare."""
    md = build_metadata(
        resource_url="https://wingman.example.com/mcp",
        tenant_id=TENANT,
        app_id_uri="https://wingman.example.com",
        required_scope="mcp.access",
    )
    assert md["scopes_supported"] == ["mcp.access"]


def test_build_metadata_uses_authorization_server_url_override():
    """When DCR shim is active, AS URL points at us, not Entra."""
    md = build_metadata(
        resource_url="https://wingman.example.com/mcp",
        tenant_id=TENANT,
        app_id_uri="api://wingman-mcp",
        required_scope="mcp.access",
        authorization_server_url="https://wingman.example.com",
    )
    assert md["authorization_servers"] == ["https://wingman.example.com"]


def test_build_metadata_empty_scope_yields_empty_list():
    md = build_metadata(
        resource_url="https://wingman.example.com/mcp",
        tenant_id=TENANT,
        app_id_uri="api://wingman-mcp",
        required_scope=None,
    )
    assert md["scopes_supported"] == []


def _scope_with(headers: dict) -> dict:
    return {
        "type": "http",
        "scheme": "http",
        "server": ("example.test", 80),
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    }


def test_resource_url_uses_override_when_set():
    url = resource_url_from_scope(
        _scope_with({"host": "ignored.example.com"}),
        public_url_override="https://canonical.example.com",
    )
    assert url == "https://canonical.example.com/mcp"


def test_resource_url_strips_trailing_slash_from_override():
    url = resource_url_from_scope(
        _scope_with({}), public_url_override="https://canonical.example.com/"
    )
    assert url == "https://canonical.example.com/mcp"


def test_resource_url_derives_from_forwarded_proto_and_host():
    url = resource_url_from_scope(
        _scope_with(
            {"x-forwarded-proto": "https", "host": "wingman.example.com"}
        ),
        public_url_override=None,
    )
    assert url == "https://wingman.example.com/mcp"


def test_resource_url_falls_back_to_scope_scheme_when_no_proto_header():
    url = resource_url_from_scope(
        _scope_with({"host": "wingman.example.com"}),
        public_url_override=None,
    )
    assert url == "http://wingman.example.com/mcp"


def test_entra_middleware_bypasses_well_known():
    mw = EntraAuthMiddleware(
        _Echo(),
        tenant_id=TENANT,
        audience="api://wingman-mcp",
        required_scope="mcp.access",
    )
    client = TestClient(mw)
    resp = client.get(PATH)
    assert resp.status_code == 200
    assert resp.text == PATH


def test_credential_middleware_bypasses_well_known():
    mw = CredentialHeaderMiddleware(_Echo())
    client = TestClient(mw)
    resp = client.get(PATH)
    assert resp.status_code == 200
    assert resp.text == PATH


@pytest.mark.parametrize(
    "path",
    [
        "/health",
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server",
        "/oauth/register",
        "/oauth/authorize",
        "/oauth/token",
    ],
)
def test_is_public_path_covers_all_unauthenticated_routes(path):
    assert is_public_path(path) is True


@pytest.mark.parametrize("path", ["/mcp", "/", "/foo", "/oauth/other", "/.well-known/foo"])
def test_is_public_path_rejects_other_routes(path):
    assert is_public_path(path) is False


def test_entra_middleware_still_rejects_unauth_for_other_paths():
    """Sanity: the bypass is path-scoped, not a blanket open door."""
    mw = EntraAuthMiddleware(
        _Echo(),
        tenant_id=TENANT,
        audience="api://wingman-mcp",
        required_scope="mcp.access",
    )
    client = TestClient(mw)
    resp = client.get("/mcp")
    assert resp.status_code == 401
