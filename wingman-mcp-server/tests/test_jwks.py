"""Tests for the JWKS cache used by EntraAuthMiddleware."""
import asyncio
import pytest

from wingman_mcp_server.jwks import JWKSCache, JWKSUnavailable


def _make_jwk(kid: str) -> dict:
    """Build a deterministic minimal RSA JWK with the given kid."""
    # Public exponent 65537 ("AQAB"). The modulus is fixed test data; the key
    # never needs to actually verify anything in this test file.
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": (
            "xGZK7uA0Q5e3w-9wn4z3kQv5W7t4iJ8tA9q3Mlxz9_3"
            "n9F-O0kJ5d5w2RDr6tj_g8RmHGAFh4uG7B2yU8mWmZ3"
            "S9D5L8r6tWqv9R7QZ1cQrL8Ah8d5jX-qF3uH3w0J7Yz"
            "9G0Y6u4n2bC5h1xX9w8a-y2zF7p7w1m5d_xj7K0e1y4"
            "vV9rX3Tn0g3y1n8b3iQ0sB1S0wQy3w_4u3Vh3lE_Yz3"
            "WgN8eZ0kQy7c8sX4i1m0gK8B3yQzQ_5z3y3p9b5j8wA"
        ),
        "e": "AQAB",
    }


class FakeHttpClient:
    """Stand-in for httpx.AsyncClient that counts calls and returns canned JWKS."""

    def __init__(self, jwks_payloads: list[dict], fail_with: Exception | None = None):
        self._payloads = jwks_payloads
        self._fail_with = fail_with
        self.call_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str):
        self.call_count += 1
        if self._fail_with is not None:
            raise self._fail_with
        idx = min(self.call_count - 1, len(self._payloads) - 1)
        body = self._payloads[idx]

        class _Resp:
            def __init__(self, b: dict):
                self._b = b

            def raise_for_status(self):
                return None

            def json(self):
                return self._b

        return _Resp(body)


@pytest.mark.asyncio
async def test_first_call_fetches_then_cache_serves_second():
    client = FakeHttpClient([{"keys": [_make_jwk("kid-1")]}])
    cache = JWKSCache(
        "https://example/jwks",
        ttl=60.0,
        http_client_factory=lambda: client,
    )

    k1 = await cache.get_key("kid-1")
    k2 = await cache.get_key("kid-1")

    assert k1 is k2
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_ttl_expiry_triggers_refetch(monkeypatch):
    client = FakeHttpClient(
        [
            {"keys": [_make_jwk("kid-1")]},
            {"keys": [_make_jwk("kid-1")]},
        ]
    )
    fake_now = [1000.0]
    monkeypatch.setattr("wingman_mcp_server.jwks.time.monotonic", lambda: fake_now[0])

    cache = JWKSCache(
        "https://example/jwks",
        ttl=60.0,
        http_client_factory=lambda: client,
    )

    await cache.get_key("kid-1")
    fake_now[0] += 61.0
    await cache.get_key("kid-1")

    assert client.call_count == 2


@pytest.mark.asyncio
async def test_unknown_kid_triggers_one_refetch_then_errors():
    client = FakeHttpClient(
        [
            {"keys": [_make_jwk("kid-old")]},
            {"keys": [_make_jwk("kid-old")]},
        ]
    )
    cache = JWKSCache(
        "https://example/jwks",
        ttl=60.0,
        http_client_factory=lambda: client,
    )

    with pytest.raises(JWKSUnavailable):
        await cache.get_key("kid-new")
    assert client.call_count == 2


@pytest.mark.asyncio
async def test_unknown_kid_found_after_refetch_returns_key():
    client = FakeHttpClient(
        [
            {"keys": [_make_jwk("kid-old")]},
            {"keys": [_make_jwk("kid-old"), _make_jwk("kid-new")]},
        ]
    )
    cache = JWKSCache(
        "https://example/jwks",
        ttl=60.0,
        http_client_factory=lambda: client,
    )

    # First call populates with kid-old only.
    await cache.get_key("kid-old")
    # kid-new not in cache; should refetch once and succeed.
    k = await cache.get_key("kid-new")
    assert k is not None
    assert client.call_count == 2


@pytest.mark.asyncio
async def test_concurrent_callers_make_one_network_call():
    client = FakeHttpClient([{"keys": [_make_jwk("kid-1")]}])
    cache = JWKSCache(
        "https://example/jwks",
        ttl=60.0,
        http_client_factory=lambda: client,
    )

    results = await asyncio.gather(*[cache.get_key("kid-1") for _ in range(10)])
    assert all(r is results[0] for r in results)
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_network_failure_raises_jwks_unavailable():
    client = FakeHttpClient([], fail_with=RuntimeError("boom"))
    cache = JWKSCache(
        "https://example/jwks",
        ttl=60.0,
        http_client_factory=lambda: client,
    )

    with pytest.raises(JWKSUnavailable):
        await cache.get_key("any-kid")
