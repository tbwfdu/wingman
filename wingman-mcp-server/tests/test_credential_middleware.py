"""Tests for CredentialHeaderMiddleware. After the Entra refactor this middleware
is only responsible for UEM credential extraction, never for access control."""
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from wingman_mcp_server.middleware import CredentialHeaderMiddleware
from wingman_mcp.request_context import _request_credentials


def _build(monkeypatch, access_key_env):
    if access_key_env is None:
        monkeypatch.delenv("WINGMAN_MCP_ACCESS_KEY", raising=False)
    else:
        monkeypatch.setenv("WINGMAN_MCP_ACCESS_KEY", access_key_env)

    captured = {}

    async def root(request):
        captured["creds"] = _request_credentials.get()
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/mcp", root), Route("/health", root)])
    return CredentialHeaderMiddleware(inner), captured


def test_no_access_key_header_passes_even_when_env_var_set(monkeypatch):
    """The middleware must no longer enforce the access key. EntraAuthMiddleware
    owns that path."""
    mw, captured = _build(monkeypatch, access_key_env="some-key")
    client = TestClient(mw)

    r = client.get("/mcp")

    assert r.status_code == 200
    assert captured["creds"] is None


def test_uem_headers_populate_credentials(monkeypatch):
    mw, captured = _build(monkeypatch, access_key_env=None)
    client = TestClient(mw)

    r = client.get(
        "/mcp",
        headers={
            "X-UEM-Client-ID": "cid",
            "X-UEM-Client-Secret": "csec",
            "X-UEM-Token-URL": "https://t/oauth/token",
            "X-UEM-API-URL": "https://api/",
        },
    )

    assert r.status_code == 200
    bundle = captured["creds"]
    assert bundle is not None
    creds = bundle["uem"]
    assert creds["client_id"] == "cid"
    assert creds["api_base_url"] == "https://api"  # trailing slash stripped


def test_horizon_headers_populate_credentials(monkeypatch):
    mw, captured = _build(monkeypatch, access_key_env=None)
    client = TestClient(mw)

    r = client.get(
        "/mcp",
        headers={
            "X-Horizon-Username": "alice",
            "X-Horizon-Password": "s3cret",
            "X-Horizon-Server-URL": "https://horizon.example.com/",
            "X-Horizon-Domain": "CORP",
        },
    )

    assert r.status_code == 200
    bundle = captured["creds"]
    assert bundle is not None
    horizon = bundle["horizon"]
    assert horizon["username"] == "alice"
    assert horizon["server_url"] == "https://horizon.example.com"
    assert horizon["domain"] == "CORP"


def test_partial_product_headers_dropped(monkeypatch):
    """If only some fields are present for a product, that product is
    omitted entirely so handlers never see a half-filled credential dict."""
    mw, captured = _build(monkeypatch, access_key_env=None)
    client = TestClient(mw)

    r = client.get(
        "/mcp",
        headers={
            # UEM is complete
            "X-UEM-Client-ID": "cid",
            "X-UEM-Client-Secret": "csec",
            "X-UEM-Token-URL": "https://t/oauth/token",
            "X-UEM-API-URL": "https://api/",
            # Horizon is missing password and domain
            "X-Horizon-Username": "alice",
            "X-Horizon-Server-URL": "https://horizon.example.com/",
        },
    )

    assert r.status_code == 200
    bundle = captured["creds"]
    assert "uem" in bundle
    assert "horizon" not in bundle


def test_multiple_products_coexist(monkeypatch):
    """A single request can carry headers for several products."""
    mw, captured = _build(monkeypatch, access_key_env=None)
    client = TestClient(mw)

    r = client.get(
        "/mcp",
        headers={
            "X-UEM-Client-ID": "u",
            "X-UEM-Client-Secret": "s",
            "X-UEM-Token-URL": "https://t",
            "X-UEM-API-URL": "https://api",
            "X-App-Volumes-Username": "av-user",
            "X-App-Volumes-Password": "av-pass",
            "X-App-Volumes-Manager-URL": "https://av",
        },
    )

    assert r.status_code == 200
    bundle = captured["creds"]
    assert set(bundle.keys()) == {"uem", "app_volumes"}
    assert bundle["app_volumes"]["username"] == "av-user"


def test_health_bypass_still_works(monkeypatch):
    mw, _ = _build(monkeypatch, access_key_env=None)
    client = TestClient(mw)

    r = client.get("/health")

    assert r.status_code == 200
