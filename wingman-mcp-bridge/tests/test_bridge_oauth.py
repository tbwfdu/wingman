"""Tests for the bridge OAuth client (wingman_mcp.oauth_client).

HTTP is mocked with httpx.MockTransport; the keychain is replaced with an
in-memory fake so nothing touches the real OS credential store.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time

import httpx
import pytest

from wingman_mcp_bridge import oauth_client as oc


# ---------------------------------------------------------------------------
# Fake keychain
# ---------------------------------------------------------------------------

class _FakeKeyringErrors:
    class PasswordDeleteError(Exception):
        pass


class _FakeKeyring:
    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}
        self.errors = _FakeKeyringErrors()

    def get_password(self, service, account):
        return self.store.get((service, account))

    def set_password(self, service, account, value):
        self.store[(service, account)] = value

    def delete_password(self, service, account):
        if (service, account) not in self.store:
            raise self.errors.PasswordDeleteError()
        del self.store[(service, account)]


@pytest.fixture
def fake_keyring(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(oc, "keyring", fake)
    return fake


REMOTE = "https://wingman.example.com/mcp"


def _bundle(**overrides) -> oc.TokenBundle:
    base = dict(
        access_token="access-abc",
        refresh_token="refresh-xyz",
        expires_at=time.time() + 3600,
        token_endpoint="https://wingman.example.com/oauth/token",
        client_id="client-123",
        scope="api://wingman-mcp/mcp.access",
    )
    base.update(overrides)
    return oc.TokenBundle(**base)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_generate_pkce_challenge_is_sha256_of_verifier():
    verifier, challenge = oc.generate_pkce()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    assert challenge == expected
    assert "=" not in verifier and "=" not in challenge


def test_generate_pkce_is_random():
    assert oc.generate_pkce()[0] != oc.generate_pkce()[0]


def test_token_needs_refresh():
    now = 1_000_000.0
    assert oc.token_needs_refresh(now + 30, now=now) is True       # within buffer
    assert oc.token_needs_refresh(now - 10, now=now) is True       # already expired
    assert oc.token_needs_refresh(now + 3600, now=now) is False    # plenty of life


def test_host_of_and_prm_url():
    assert oc.host_of(REMOTE) == "wingman.example.com"
    assert oc.prm_url(REMOTE) == (
        "https://wingman.example.com/.well-known/oauth-protected-resource"
    )


def test_host_of_rejects_url_without_host():
    with pytest.raises(ValueError):
        oc.host_of("not-a-url")


# ---------------------------------------------------------------------------
# Token cache round-trip
# ---------------------------------------------------------------------------

def test_token_bundle_json_round_trip():
    b = _bundle()
    assert oc.TokenBundle.from_json(b.to_json()) == b


def test_store_load_clear_bundle(fake_keyring):
    assert oc.load_bundle(REMOTE) is None
    b = _bundle()
    oc.store_bundle(REMOTE, b)
    assert oc.load_bundle(REMOTE) == b
    oc.clear_bundle(REMOTE)
    assert oc.load_bundle(REMOTE) is None


def test_clear_bundle_is_idempotent(fake_keyring):
    oc.clear_bundle(REMOTE)  # nothing cached — must not raise


def test_load_bundle_tolerates_corrupt_json(fake_keyring):
    fake_keyring.set_password(f"{oc.OAUTH_SERVICE_BASE}.{oc.host_of(REMOTE)}",
                              "bundle", "{garbage")
    assert oc.load_bundle(REMOTE) is None


def test_bundles_are_namespaced_per_host(fake_keyring):
    oc.store_bundle("https://a.example.com/mcp", _bundle(access_token="A"))
    oc.store_bundle("https://b.example.com/mcp", _bundle(access_token="B"))
    assert oc.load_bundle("https://a.example.com/mcp").access_token == "A"
    assert oc.load_bundle("https://b.example.com/mcp").access_token == "B"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _discovery_transport(prm_status=200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == oc.PRM_PATH:
            if prm_status != 200:
                return httpx.Response(prm_status)
            return httpx.Response(200, json={
                "resource": REMOTE,
                "authorization_servers": ["https://wingman.example.com"],
                "scopes_supported": ["api://wingman-mcp/mcp.access"],
            })
        if path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={
                "authorization_endpoint": "https://wingman.example.com/oauth/authorize",
                "token_endpoint": "https://wingman.example.com/oauth/token",
                "registration_endpoint": "https://wingman.example.com/oauth/register",
            })
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_discover_resolves_endpoints():
    async with httpx.AsyncClient(transport=_discovery_transport()) as client:
        disc = await oc.discover(REMOTE, client=client)
    assert disc.authorization_endpoint == "https://wingman.example.com/oauth/authorize"
    assert disc.token_endpoint == "https://wingman.example.com/oauth/token"
    assert disc.registration_endpoint == "https://wingman.example.com/oauth/register"
    assert disc.scopes_supported == ["api://wingman-mcp/mcp.access"]


@pytest.mark.asyncio
async def test_discover_raises_on_missing_prm():
    async with httpx.AsyncClient(transport=_discovery_transport(prm_status=404)) as client:
        with pytest.raises(oc.OAuthError, match="protected-resource discovery failed"):
            await oc.discover(REMOTE, client=client)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_client_returns_client_id():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"client_id": "entra-cid-999"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cid = await oc.register_client(
            "https://wingman.example.com/oauth/register",
            redirect_uri="http://localhost:5000/callback",
            client=client,
        )
    assert cid == "entra-cid-999"
    assert captured["body"]["redirect_uris"] == ["http://localhost:5000/callback"]


@pytest.mark.asyncio
async def test_register_client_raises_without_client_id():
    def handler(request):
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(oc.OAuthError, match="no client_id"):
            await oc.register_client(
                "https://wingman.example.com/oauth/register",
                redirect_uri="http://localhost:5000/callback",
                client=client,
            )


# ---------------------------------------------------------------------------
# Code exchange + refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exchange_code_builds_bundle():
    def handler(request: httpx.Request) -> httpx.Response:
        form = dict(httpx.QueryParams(request.content.decode()))
        assert form["grant_type"] == "authorization_code"
        assert form["code_verifier"] == "verifier-1"
        return httpx.Response(200, json={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        bundle = await oc.exchange_code(
            token_endpoint="https://wingman.example.com/oauth/token",
            client_id="cid",
            code="the-code",
            code_verifier="verifier-1",
            redirect_uri="http://localhost:5000/callback",
            scope="api://wingman-mcp/mcp.access",
            client=client,
        )
    assert bundle.access_token == "new-access"
    assert bundle.refresh_token == "new-refresh"
    assert bundle.expires_at > time.time()


@pytest.mark.asyncio
async def test_refresh_bundle_keeps_old_refresh_token_when_absent():
    def handler(request):
        return httpx.Response(200, json={
            "access_token": "refreshed-access",
            "expires_in": 3600,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        refreshed = await oc.refresh_bundle(_bundle(refresh_token="keep-me"), client=client)
    assert refreshed.access_token == "refreshed-access"
    assert refreshed.refresh_token == "keep-me"


@pytest.mark.asyncio
async def test_refresh_bundle_failure_raises_not_logged_in():
    def handler(request):
        return httpx.Response(400, json={"error": "invalid_grant"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(oc.NotLoggedIn, match="wingman-mcp login"):
            await oc.refresh_bundle(_bundle(), client=client)


# ---------------------------------------------------------------------------
# get_access_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_access_token_returns_cached_when_valid(fake_keyring):
    oc.store_bundle(REMOTE, _bundle(access_token="still-good"))
    token = await oc.get_access_token(REMOTE)
    assert token == "still-good"


@pytest.mark.asyncio
async def test_get_access_token_refreshes_when_expired(fake_keyring):
    oc.store_bundle(REMOTE, _bundle(access_token="stale", expires_at=time.time() - 5))

    def handler(request):
        return httpx.Response(200, json={
            "access_token": "fresh-token", "expires_in": 3600,
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        token = await oc.get_access_token(REMOTE, client=client)
    assert token == "fresh-token"
    # The refreshed bundle is persisted back to the keychain.
    assert oc.load_bundle(REMOTE).access_token == "fresh-token"


@pytest.mark.asyncio
async def test_get_access_token_raises_when_not_cached(fake_keyring):
    with pytest.raises(oc.NotLoggedIn, match="wingman-mcp login"):
        await oc.get_access_token(REMOTE)
