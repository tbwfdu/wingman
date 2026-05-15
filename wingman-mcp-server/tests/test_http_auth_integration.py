"""End-to-end test of the HTTP middleware stack: Entra auth in front of
credential extraction."""
import base64
import time

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
from wingman_mcp_server.middleware import CredentialHeaderMiddleware
from wingman_mcp.request_context import _request_credentials, _request_principal
from wingman_mcp_server.http_server import _validate_http_auth_config


TENANT = "11111111-1111-1111-1111-111111111111"
AUDIENCE = "api://wingman-mcp"


@pytest.fixture(scope="module")
def keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pn = priv.public_key().public_numbers()

    def _b64uint(i: int) -> str:
        b = i.to_bytes((i.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "kid": "test-kid",
        "use": "sig",
        "alg": "RS256",
        "n": _b64uint(pn.n),
        "e": _b64uint(pn.e),
    }
    return priv_pem, jwk


class _Boom:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        raise AssertionError("must not hit network")


def test_full_stack_sets_both_principal_and_credentials(keypair):
    priv, jwk = keypair
    captured = {}

    async def root(request):
        captured["principal"] = _request_principal.get()
        captured["creds"] = _request_credentials.get()
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/mcp", root)])

    cache = JWKSCache("https://unused", http_client_factory=lambda: _Boom())
    cache._keys = {"test-kid": jwt.PyJWK(jwk)}
    cache._fetched_at = time.monotonic()

    creds_mw = CredentialHeaderMiddleware(inner)
    auth_mw = EntraAuthMiddleware(
        creds_mw,
        tenant_id=TENANT,
        audience=AUDIENCE,
        required_scope="mcp.access",
        jwks_cache=cache,
    )
    client = TestClient(auth_mw)

    now = int(time.time())
    token = jwt.encode(
        {
            "aud": AUDIENCE,
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "tid": TENANT,
            "oid": "u-1",
            "scp": "mcp.access",
            "iat": now,
            "nbf": now,
            "exp": now + 600,
            "preferred_username": "u@example.com",
        },
        priv,
        algorithm="RS256",
        headers={"kid": "test-kid"},
    )

    r = client.get(
        "/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "X-UEM-Client-ID": "cid",
            "X-UEM-Client-Secret": "csec",
            "X-UEM-Token-URL": "https://t/oauth/token",
            "X-UEM-API-URL": "https://api/",
        },
    )

    assert r.status_code == 200
    p = captured["principal"]
    assert p is not None and p.auth_method == "entra" and p.oid == "u-1"
    bundle = captured["creds"]
    assert bundle is not None and bundle["uem"]["client_id"] == "cid"


def test_boot_guard_raises_when_no_auth_path_configured(monkeypatch):
    monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
    monkeypatch.delenv("WINGMAN_MCP_ACCESS_KEY", raising=False)
    with pytest.raises(SystemExit):
        _validate_http_auth_config()


def test_boot_guard_passes_with_only_tenant(monkeypatch):
    monkeypatch.setenv("ENTRA_TENANT_ID", "abc")
    monkeypatch.delenv("WINGMAN_MCP_ACCESS_KEY", raising=False)
    _validate_http_auth_config()


def test_boot_guard_passes_with_only_static_key(monkeypatch):
    monkeypatch.delenv("ENTRA_TENANT_ID", raising=False)
    monkeypatch.setenv("WINGMAN_MCP_ACCESS_KEY", "s")
    _validate_http_auth_config()
