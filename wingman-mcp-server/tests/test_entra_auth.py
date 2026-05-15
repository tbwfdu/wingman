"""Tests for EntraAuthMiddleware. Uses a locally generated RSA keypair to
mint test tokens; no network calls."""
import base64
import time
from typing import Optional

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from wingman_mcp_server.entra_auth import EntraAuthMiddleware
from wingman_mcp_server.jwks import JWKSCache
from wingman_mcp.request_context import _request_principal


TENANT = "00000000-0000-0000-0000-000000000001"
AUDIENCE = "api://wingman-mcp"
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"


@pytest.fixture(scope="module")
def keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_numbers = priv.public_key().public_numbers()

    def _b64uint(i: int) -> str:
        b = i.to_bytes((i.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "kid": "test-kid",
        "use": "sig",
        "alg": "RS256",
        "n": _b64uint(pub_numbers.n),
        "e": _b64uint(pub_numbers.e),
    }
    return priv_pem, jwk


def _make_token(
    priv_pem: bytes,
    *,
    aud: str = AUDIENCE,
    iss: str = ISSUER,
    tid: str = TENANT,
    oid: str = "user-oid-1",
    scp: str = "mcp.access",
    exp_offset: int = 600,
    extra_claims: Optional[dict] = None,
) -> str:
    now = int(time.time())
    payload = {
        "aud": aud,
        "iss": iss,
        "tid": tid,
        "oid": oid,
        "scp": scp,
        "iat": now,
        "nbf": now,
        "exp": now + exp_offset,
        "preferred_username": "user@example.com",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, priv_pem, algorithm="RS256", headers={"kid": "test-kid"})


class _Unused:
    """JWKS client that fails loudly if anything tries to use it."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        raise AssertionError("network must not be used in this test")


def _build_app(
    keypair_jwk: dict,
    *,
    tenant_id: Optional[str] = TENANT,
    audience: str = AUDIENCE,
    required_scope: str = "mcp.access",
    static_access_key: Optional[str] = None,
):
    captured = {}

    async def root(request):
        captured["principal"] = _request_principal.get()
        return PlainTextResponse("ok")

    async def health(request):
        captured["principal"] = _request_principal.get()
        return PlainTextResponse("healthy")

    inner = Starlette(routes=[Route("/mcp", root), Route("/health", health)])

    cache = JWKSCache("https://unused", http_client_factory=lambda: _Unused())
    cache._keys = {keypair_jwk["kid"]: jwt.PyJWK(keypair_jwk)}
    cache._fetched_at = time.monotonic()

    mw = EntraAuthMiddleware(
        inner,
        tenant_id=tenant_id,
        audience=audience,
        required_scope=required_scope,
        static_access_key=static_access_key,
        jwks_cache=cache,
    )
    return mw, captured


def test_valid_token_passes_and_sets_principal(keypair):
    priv, jwk = keypair
    mw, captured = _build_app(jwk)
    client = TestClient(mw)
    token = _make_token(priv)

    r = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
    p = captured["principal"]
    assert p is not None
    assert p.auth_method == "entra"
    assert p.oid == "user-oid-1"
    assert p.upn == "user@example.com"
    assert p.tid == TENANT


def test_expired_token_returns_401_invalid_token(keypair):
    priv, jwk = keypair
    mw, _ = _build_app(jwk)
    client = TestClient(mw)
    token = _make_token(priv, exp_offset=-120)

    r = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"
    assert 'error="invalid_token"' in r.headers["www-authenticate"]


def test_wrong_audience_returns_401(keypair):
    priv, jwk = keypair
    mw, _ = _build_app(jwk)
    client = TestClient(mw)
    token = _make_token(priv, aud="api://something-else")

    r = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"


def test_audience_mismatch_log_includes_actual_and_expected(keypair, caplog):
    """The rejection log should name both what we got and what we wanted,
    so operators don't have to manually JWT-decode to diagnose."""
    import logging
    priv, jwk = keypair
    mw, _ = _build_app(jwk)
    client = TestClient(mw)
    token = _make_token(priv, aud="api://wrong-audience")

    with caplog.at_level(logging.WARNING, logger="wingman_mcp_server.entra_auth"):
        r = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 401
    log_text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert AUDIENCE in log_text                # expected
    assert "api://wrong-audience" in log_text  # actual


def test_wrong_issuer_returns_401(keypair):
    priv, jwk = keypair
    mw, _ = _build_app(jwk)
    client = TestClient(mw)
    token = _make_token(priv, iss="https://login.microsoftonline.com/bad/v2.0")

    r = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"


def test_wrong_tenant_id_returns_401(keypair):
    """tid defense-in-depth: issuer matches the configured tenant but the
    `tid` claim does not."""
    priv, jwk = keypair
    mw, _ = _build_app(jwk)
    client = TestClient(mw)
    token = _make_token(priv, tid="bad-tenant")

    r = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"


def test_missing_required_scope_returns_403(keypair):
    priv, jwk = keypair
    mw, _ = _build_app(jwk)
    client = TestClient(mw)
    token = _make_token(priv, scp="something.else")

    r = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 403
    assert r.json()["error"] == "insufficient_scope"
    assert "insufficient_scope" in r.headers["www-authenticate"]


def test_malformed_authorization_header_returns_401(keypair):
    _, jwk = keypair
    mw, _ = _build_app(jwk)
    client = TestClient(mw)

    r = client.get("/mcp", headers={"Authorization": "NotBearer xxx"})

    assert r.status_code == 401
    assert r.json()["error"] == "invalid_request"


def test_no_auth_header_static_key_disabled_returns_401(keypair):
    _, jwk = keypair
    mw, _ = _build_app(jwk, static_access_key=None)
    client = TestClient(mw)

    r = client.get("/mcp")

    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_no_auth_header_static_key_match_succeeds(keypair):
    _, jwk = keypair
    mw, captured = _build_app(jwk, static_access_key="s3cret")
    client = TestClient(mw)

    r = client.get("/mcp", headers={"X-Wingman-Access-Key": "s3cret"})

    assert r.status_code == 200
    p = captured["principal"]
    assert p.auth_method == "static_key"
    assert p.oid is None


def test_no_auth_header_static_key_mismatch_returns_401(keypair):
    _, jwk = keypair
    mw, _ = _build_app(jwk, static_access_key="s3cret")
    client = TestClient(mw)

    r = client.get("/mcp", headers={"X-Wingman-Access-Key": "wrong"})

    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"


def test_health_path_bypasses_auth(keypair):
    _, jwk = keypair
    mw, _ = _build_app(jwk)
    client = TestClient(mw)

    r = client.get("/health")

    assert r.status_code == 200


def test_required_scope_empty_string_skips_check(keypair):
    """Operators can disable the scope check by setting ENTRA_REQUIRED_SCOPE=''."""
    priv, jwk = keypair
    mw, _ = _build_app(jwk, required_scope="")
    client = TestClient(mw)
    token = _make_token(priv, scp="")

    r = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
