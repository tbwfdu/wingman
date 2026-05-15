"""Tests for the OAuth DCR shim in src/wingman_mcp/oauth_shim.py."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from wingman_mcp_server.oauth_shim import (
    AS_METADATA_PATH,
    AUTHORIZE_PATH,
    REGISTER_PATH,
    TOKEN_PATH,
    build_as_metadata,
    build_register_response,
    entra_authorize_url,
    proxy_token_request,
)


TENANT = "11111111-1111-1111-1111-111111111111"
CLIENT_ID = "22222222-2222-2222-2222-222222222222"


def test_as_metadata_points_endpoints_at_our_issuer():
    md = build_as_metadata(
        issuer_url="https://wingman.example.com",
        scopes_supported=["api://wingman-mcp/mcp.access"],
    )
    assert md["issuer"] == "https://wingman.example.com"
    assert md["authorization_endpoint"] == f"https://wingman.example.com{AUTHORIZE_PATH}"
    assert md["token_endpoint"] == f"https://wingman.example.com{TOKEN_PATH}"
    assert md["registration_endpoint"] == f"https://wingman.example.com{REGISTER_PATH}"
    assert md["response_types_supported"] == ["code"]
    assert "authorization_code" in md["grant_types_supported"]
    assert "refresh_token" in md["grant_types_supported"]
    assert md["code_challenge_methods_supported"] == ["S256"]
    assert md["token_endpoint_auth_methods_supported"] == ["none"]
    assert md["scopes_supported"] == ["api://wingman-mcp/mcp.access"]


def test_as_metadata_strips_trailing_slash():
    md = build_as_metadata(
        issuer_url="https://wingman.example.com/",
        scopes_supported=["s"],
    )
    assert md["issuer"] == "https://wingman.example.com"
    assert md["authorization_endpoint"].startswith("https://wingman.example.com/")


def test_register_returns_static_client_id():
    resp = build_register_response(
        client_id=CLIENT_ID,
        request_body={
            "redirect_uris": ["http://localhost:6274/oauth/callback"],
            "client_name": "test-client",
        },
    )
    assert resp["client_id"] == CLIENT_ID
    assert resp["redirect_uris"] == ["http://localhost:6274/oauth/callback"]
    assert resp["client_name"] == "test-client"
    assert resp["token_endpoint_auth_method"] == "none"
    assert "authorization_code" in resp["grant_types"]
    assert isinstance(resp["client_id_issued_at"], int)


def test_register_tolerates_missing_metadata():
    resp = build_register_response(client_id=CLIENT_ID, request_body={})
    assert resp["client_id"] == CLIENT_ID
    assert "redirect_uris" not in resp
    assert "client_name" not in resp


def test_authorize_url_targets_entra_v2_with_passthrough():
    url = entra_authorize_url(
        tenant_id=TENANT,
        app_id_uri="api://wingman-mcp",
        query_params={
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": "http://localhost:6274/oauth/callback",
            "scope": "api://wingman-mcp/mcp.access",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
            "state": "xyz",
        },
    )
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "login.microsoftonline.com"
    assert parsed.path == f"/{TENANT}/oauth2/v2.0/authorize"
    q = parse_qs(parsed.query)
    assert q["response_type"] == ["code"]
    assert q["client_id"] == [CLIENT_ID]
    assert q["code_challenge"] == ["abc"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["state"] == ["xyz"]


def test_authorize_url_appends_offline_access():
    url = entra_authorize_url(
        tenant_id=TENANT,
        app_id_uri="api://wingman-mcp",
        query_params={"scope": "api://wingman-mcp/mcp.access"},
    )
    scope = parse_qs(urlparse(url).query)["scope"][0].split()
    assert "api://wingman-mcp/mcp.access" in scope
    assert "offline_access" in scope


def test_authorize_url_does_not_duplicate_offline_access():
    url = entra_authorize_url(
        tenant_id=TENANT,
        app_id_uri="api://wingman-mcp",
        query_params={"scope": "api://wingman-mcp/mcp.access offline_access"},
    )
    scope = parse_qs(urlparse(url).query)["scope"][0].split()
    assert scope.count("offline_access") == 1


def test_authorize_url_qualifies_unqualified_scope_using_app_id_uri():
    """Claude Desktop sends bare scope=mcp.access + resource=<server URL>.
    The shim ignores the client-provided resource and qualifies using the
    configured App ID URI, which is the only value guaranteed to resolve
    to an Entra resource principal."""
    url = entra_authorize_url(
        tenant_id=TENANT,
        app_id_uri="api://wingman-mcp",
        query_params={
            "client_id": CLIENT_ID,
            "scope": "mcp.access",
            "resource": "https://wingman.example.com/mcp",
            "state": "x",
        },
    )
    q = parse_qs(urlparse(url).query)
    assert "resource" not in q
    parts = q["scope"][0].split()
    assert "api://wingman-mcp/mcp.access" in parts
    assert "mcp.access" not in parts
    assert "https://wingman.example.com/mcp/mcp.access" not in parts
    assert "offline_access" in parts


def test_authorize_url_leaves_already_qualified_scope_alone():
    """mcp-remote sends the fully-qualified form. We must not double-prefix."""
    url = entra_authorize_url(
        tenant_id=TENANT,
        app_id_uri="api://wingman-mcp",
        query_params={"scope": "api://wingman-mcp/mcp.access"},
    )
    parts = parse_qs(urlparse(url).query)["scope"][0].split()
    assert parts.count("api://wingman-mcp/mcp.access") == 1


def test_authorize_url_preserves_special_scopes_during_qualification():
    """offline_access / openid / profile / email are universal and must
    never get a resource prefix."""
    url = entra_authorize_url(
        tenant_id=TENANT,
        app_id_uri="api://wingman-mcp",
        query_params={"scope": "mcp.access openid offline_access profile"},
    )
    parts = parse_qs(urlparse(url).query)["scope"][0].split()
    assert "api://wingman-mcp/mcp.access" in parts
    assert "openid" in parts
    assert "offline_access" in parts
    assert "profile" in parts
    assert "api://wingman-mcp/openid" not in parts


def test_authorize_url_strips_rfc8707_resource_param():
    """Entra v2 rejects requests that include `resource` (AADSTS9010010).
    mcp-remote and Claude Desktop both send it per the MCP auth draft;
    the shim must drop it on the way out regardless of value."""
    url = entra_authorize_url(
        tenant_id=TENANT,
        app_id_uri="api://wingman-mcp",
        query_params={
            "client_id": CLIENT_ID,
            "scope": "api://wingman-mcp/mcp.access",
            "resource": "https://wingman.example.com/mcp",
            "state": "xyz",
        },
    )
    q = parse_qs(urlparse(url).query)
    assert "resource" not in q
    assert q["scope"][0].split() == ["api://wingman-mcp/mcp.access", "offline_access"]
    assert q["client_id"] == [CLIENT_ID]
    assert q["state"] == ["xyz"]


def test_authorize_url_handles_empty_scope():
    url = entra_authorize_url(
        tenant_id=TENANT, app_id_uri="api://wingman-mcp", query_params={}
    )
    scope = parse_qs(urlparse(url).query)["scope"][0].split()
    assert scope == ["offline_access"]


@pytest.mark.asyncio
async def test_proxy_token_request_forwards_body_to_entra():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = request.content
        captured["content_type"] = request.headers.get("Content-Type")
        return httpx.Response(
            200,
            json={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        body = b"grant_type=authorization_code&code=AC123&code_verifier=VER"
        resp = await proxy_token_request(
            tenant_id=TENANT,
            app_id_uri="api://wingman-mcp",
            form_body=body,
            content_type="application/x-www-form-urlencoded",
            client=client,
        )
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "tok"
    assert captured["method"] == "POST"
    assert captured["url"] == (
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"
    )
    assert captured["body"] == body
    assert captured["content_type"] == "application/x-www-form-urlencoded"


@pytest.mark.asyncio
async def test_proxy_token_request_qualifies_scope_using_app_id_uri():
    """Token-endpoint qualification mirrors the authorize endpoint:
    ignore the request's `resource` (a server URL, not an Entra resource
    principal) and use the configured App ID URI."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"access_token": "t"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await proxy_token_request(
            tenant_id=TENANT,
            app_id_uri="api://wingman-mcp",
            form_body=(
                b"grant_type=refresh_token&refresh_token=RT&"
                b"scope=mcp.access&resource=https%3A%2F%2Fwingman.example.com%2Fmcp"
            ),
            content_type="application/x-www-form-urlencoded",
            client=client,
        )
    body_str = captured["body"].decode("utf-8")
    assert "resource=" not in body_str
    assert "scope=api%3A%2F%2Fwingman-mcp%2Fmcp.access" in body_str
    assert "wingman.example.com" not in body_str  # untrusted prefix not used


@pytest.mark.asyncio
async def test_proxy_token_request_strips_resource_field():
    """Same AADSTS9010010 fix at the token endpoint: drop `resource` from
    the form body before forwarding."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(200, json={"access_token": "t"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await proxy_token_request(
            tenant_id=TENANT,
            app_id_uri="api://wingman-mcp",
            form_body=(
                b"grant_type=authorization_code&code=AC&"
                b"resource=https%3A%2F%2Fwingman.example.com%2Fmcp&code_verifier=V"
            ),
            content_type="application/x-www-form-urlencoded",
            client=client,
        )
    body_str = captured["body"].decode("utf-8")
    assert "resource=" not in body_str
    assert "grant_type=authorization_code" in body_str
    assert "code=AC" in body_str
    assert "code_verifier=V" in body_str


@pytest.mark.asyncio
async def test_proxy_token_request_propagates_entra_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "PKCE verifier mismatch",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await proxy_token_request(
            tenant_id=TENANT,
            app_id_uri="api://wingman-mcp",
            form_body=b"grant_type=authorization_code&code=bad",
            content_type="application/x-www-form-urlencoded",
            client=client,
        )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"
