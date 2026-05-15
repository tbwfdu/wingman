# Entra ID Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Entra ID JWT validation to the HTTP transport of wingman-mcp via a new `EntraAuthMiddleware` mounted in front of the existing `CredentialHeaderMiddleware`. Keep the static-access-key path as an opt-in fallback. Single-tenant only. No RBAC yet.

**Architecture:** A dedicated ASGI middleware (`EntraAuthMiddleware`) validates `Authorization: Bearer <jwt>` against the configured Entra tenant before requests reach the rest of the stack. A small caching JWKS fetcher (`JWKSCache`) backs the validation. `CredentialHeaderMiddleware` keeps reading `X-UEM-*` headers but loses its static-key check (now owned by the new middleware). A new `Principal` ContextVar lets tools see who called them.

**Tech Stack:** Python 3.10+, Starlette ASGI, httpx (async), PyJWT 2.x with crypto backend, pytest. See `docs/superpowers/specs/2026-05-14-entra-id-auth-design.md` for full design context.

---

## File Structure

**New files:**
- `src/wingman_mcp/entra_auth.py`: `EntraAuthMiddleware` (identity), `Principal` dataclass, error response helpers.
- `src/wingman_mcp/jwks.py`: `JWKSCache` async fetcher with TTL and stampede protection. `JWKSUnavailable` exception.
- `tests/test_jwks.py`: unit tests for the cache.
- `tests/test_entra_auth.py`: unit tests for the middleware (uses a generated RSA keypair to mint test tokens).
- `tests/test_http_auth_integration.py`: wires both middlewares together end-to-end with a stub inner app.
- `tests/test_request_context.py`: sanity check for the new ContextVar default.

**Modified files:**
- `src/wingman_mcp/request_context.py`: add `Principal` dataclass and `_request_principal` ContextVar.
- `src/wingman_mcp/middleware.py`: remove static-access-key check; keep `/health` bypass and `X-UEM-*` extraction.
- `src/wingman_mcp/server.py`: extract `_validate_http_auth_config()` helper; mount `EntraAuthMiddleware` in front of `CredentialHeaderMiddleware` inside `run_http_server`.
- `pyproject.toml`: add `pyjwt[crypto]>=2.8.0` to `[project.optional-dependencies].cloud`.
- `README.md`: document new env vars in the cloud / HTTP mode section.

---

## Task 1: Add PyJWT dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Edit pyproject.toml to add PyJWT to the `cloud` extra**

Find this block in `pyproject.toml`:

```toml
cloud = [
    "starlette>=0.40.0",
    "uvicorn>=0.30.0",
]
```

Replace with:

```toml
cloud = [
    "starlette>=0.40.0",
    "uvicorn>=0.30.0",
    "pyjwt[crypto]>=2.8.0",
]
```

- [ ] **Step 2: Install the new dependency into the local venv**

Run: `cd /Users/pete/GitHub_EUC/wingman/wingman-mcp && .venv/bin/pip install -e ".[cloud,dev]"`
Expected: `Successfully installed pyjwt-... cryptography-...` (or already-satisfied).

- [ ] **Step 3: Sanity-check the import works**

Run: `.venv/bin/python -c "import jwt; from jwt import PyJWK; print(jwt.__version__)"`
Expected: prints a version string `>=2.8`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "Add pyjwt[crypto] to cloud extras for Entra ID JWT validation"
```

---

## Task 2: Add `Principal` and `_request_principal` ContextVar

**Files:**
- Modify: `src/wingman_mcp/request_context.py`
- Create: `tests/test_request_context.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_request_context.py`:

```python
"""Sanity tests for per-request context variables."""
from wingman_mcp.request_context import (
    Principal,
    _is_http_request,
    _request_credentials,
    _request_principal,
)


def test_request_principal_defaults_to_none():
    assert _request_principal.get() is None


def test_principal_dataclass_is_frozen_and_holds_fields():
    p = Principal(oid="abc", tid="t1", upn="user@example.com", auth_method="entra")
    assert p.oid == "abc"
    assert p.tid == "t1"
    assert p.upn == "user@example.com"
    assert p.auth_method == "entra"

    try:
        p.oid = "changed"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Principal should be frozen")


def test_static_key_principal_allows_none_identity_fields():
    p = Principal(oid=None, tid=None, upn=None, auth_method="static_key")
    assert p.auth_method == "static_key"
    assert p.oid is None


def test_existing_contextvars_still_present():
    assert _is_http_request.get() is False
    assert _request_credentials.get() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_request_context.py -v`
Expected: FAIL with `ImportError: cannot import name 'Principal'` or `'_request_principal'`.

- [ ] **Step 3: Implement the dataclass and ContextVar**

Replace the entire contents of `src/wingman_mcp/request_context.py` with:

```python
"""Per-request context variables for HTTP server mode.

These ContextVars are set by EntraAuthMiddleware and CredentialHeaderMiddleware
before each MCP request is dispatched, allowing call_tool handlers to access
the caller's identity and UEM credentials without any server-side storage.
"""
import contextvars
from dataclasses import dataclass
from typing import Literal, Optional

# Set to True for every HTTP request; False (default) in local stdio mode.
_is_http_request: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "is_http_request", default=False
)

# Set to a UEMCredentials dict when all four X-UEM-* headers are present,
# or None when the headers are absent (RAG-only requests are still allowed).
_request_credentials: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "request_credentials", default=None
)


@dataclass(frozen=True)
class Principal:
    """Verified identity of the HTTP caller for a single request.

    Set by EntraAuthMiddleware. `oid`, `tid`, `upn` come from the validated
    Entra JWT; they are all None when `auth_method == "static_key"`.
    """

    oid: Optional[str]
    tid: Optional[str]
    upn: Optional[str]
    auth_method: Literal["entra", "static_key"]


# Set by EntraAuthMiddleware on every authenticated HTTP request; None in
# stdio mode or before the middleware has run.
_request_principal: contextvars.ContextVar[Optional[Principal]] = contextvars.ContextVar(
    "request_principal", default=None
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_request_context.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/request_context.py tests/test_request_context.py
git commit -m "Add Principal dataclass and _request_principal ContextVar"
```

---

## Task 3: JWKS cache module

**Files:**
- Create: `src/wingman_mcp/jwks.py`
- Create: `tests/test_jwks.py`

The cache is async-only (the middleware is async). It uses `httpx.AsyncClient` for the network call and exposes a `key_provider` injection point so tests can avoid hitting the network.

- [ ] **Step 1: Write failing tests**

Create `tests/test_jwks.py`:

```python
"""Tests for the JWKS cache used by EntraAuthMiddleware."""
import asyncio
import json
import time
import pytest

from wingman_mcp.jwks import JWKSCache, JWKSUnavailable


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
    monkeypatch.setattr("wingman_mcp.jwks.time.monotonic", lambda: fake_now[0])

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
```

- [ ] **Step 2: Add pytest-asyncio to the dev extras (required for `@pytest.mark.asyncio`)**

Edit `pyproject.toml`. Replace:

```toml
dev = [
    "pytest>=8.0.0",
]
```

With:

```toml
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]
```

Add a top-level `[tool.pytest.ini_options]` setting `asyncio_mode = "auto"` is **not** what we want (it could conflict with sync tests); leave the markers explicit.

Add this to the existing `[tool.pytest.ini_options]` block so the marker doesn't trigger an "unknown marker" warning:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-q"
asyncio_mode = "strict"
markers = [
    "asyncio: mark test as an asyncio coroutine",
]
```

Then install:

Run: `.venv/bin/pip install -e ".[cloud,dev]"`
Expected: pytest-asyncio installed.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_jwks.py -v`
Expected: collection error or all 6 tests FAIL with `ImportError: No module named 'wingman_mcp.jwks'`.

- [ ] **Step 4: Implement the JWKS cache**

Create `src/wingman_mcp/jwks.py`:

```python
"""Async JWKS cache for Entra ID public keys.

Used by EntraAuthMiddleware to fetch and verify the signing key for
each incoming bearer token. Caches keys in memory with a TTL and
serializes concurrent refetches with an asyncio lock.
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable, Dict, Optional

import httpx
import jwt


class JWKSUnavailable(Exception):
    """Raised when JWKS cannot be fetched or the requested kid is absent."""


class JWKSCache:
    """In-memory JWKS cache keyed by `kid`.

    The cache holds parsed PyJWK objects keyed by Key ID. On a `kid` miss the
    cache refetches once (handles key rotation) before raising. A single
    asyncio.Lock serializes refetches so concurrent cold-start callers issue
    one network request.
    """

    def __init__(
        self,
        jwks_url: str,
        *,
        ttl: float = 3600.0,
        http_client_factory: Optional[Callable[[], httpx.AsyncClient]] = None,
    ) -> None:
        self._url = jwks_url
        self._ttl = ttl
        self._keys: Dict[str, jwt.PyJWK] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()
        self._http_client_factory = http_client_factory or (
            lambda: httpx.AsyncClient(timeout=10.0)
        )

    def _is_fresh(self) -> bool:
        return (time.monotonic() - self._fetched_at) < self._ttl

    async def get_key(self, kid: str) -> jwt.PyJWK:
        if kid in self._keys and self._is_fresh():
            return self._keys[kid]

        async with self._lock:
            # Re-check under the lock: another task may have just refetched.
            if kid in self._keys and self._is_fresh():
                return self._keys[kid]

            await self._refetch()

            if kid not in self._keys:
                # Possible key rotation: refetch once more before giving up.
                await self._refetch()

            if kid not in self._keys:
                raise JWKSUnavailable(f"kid {kid!r} not present in JWKS at {self._url}")

            return self._keys[kid]

    async def _refetch(self) -> None:
        try:
            async with self._http_client_factory() as client:
                resp = await client.get(self._url)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            raise JWKSUnavailable(f"failed to fetch JWKS from {self._url}: {exc}") from exc

        new_keys: Dict[str, jwt.PyJWK] = {}
        for jwk_dict in data.get("keys", []):
            kid = jwk_dict.get("kid")
            if not kid:
                continue
            try:
                new_keys[kid] = jwt.PyJWK(jwk_dict)
            except Exception:
                # Skip malformed keys rather than failing the whole refetch.
                continue
        self._keys = new_keys
        self._fetched_at = time.monotonic()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_jwks.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/wingman_mcp/jwks.py tests/test_jwks.py
git commit -m "Add JWKSCache with TTL and stampede-protected refetch"
```

---

## Task 4: EntraAuthMiddleware

**Files:**
- Create: `src/wingman_mcp/entra_auth.py`
- Create: `tests/test_entra_auth.py`

The middleware accepts dependencies via constructor so tests can inject a `JWKSCache` populated with a locally generated RSA keypair.

- [ ] **Step 1: Write failing tests**

Create `tests/test_entra_auth.py`:

```python
"""Tests for EntraAuthMiddleware. Uses a locally generated RSA keypair to
mint test tokens; no network calls."""
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

from wingman_mcp.entra_auth import EntraAuthMiddleware
from wingman_mcp.jwks import JWKSCache
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
    # Build a JWK dict matching the kid we will sign with.
    import base64

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

    # Build a pre-populated JWKSCache that never hits the network.
    cache = JWKSCache(
        "https://unused",
        http_client_factory=lambda: _Unused(),
    )
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


class _Unused:
    """JWKS client that fails loudly if anything tries to use it."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        raise AssertionError("network must not be used in this test")


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
    token = _make_token(priv, exp_offset=-10)

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


def test_wrong_issuer_returns_401(keypair):
    priv, jwk = keypair
    mw, _ = _build_app(jwk)
    client = TestClient(mw)
    token = _make_token(priv, iss="https://login.microsoftonline.com/bad/v2.0")

    r = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 401
    assert r.json()["error"] == "invalid_token"


def test_wrong_tenant_id_returns_401(keypair):
    """tid defense-in-depth: issuer can match the configured tenant but the
    `tid` claim must too."""
    priv, jwk = keypair
    mw, _ = _build_app(jwk)
    client = TestClient(mw)
    # Sign with the right issuer but a tampered tid.
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
    # Token with no scp claim at all
    token = _make_token(priv, scp="")

    r = client.get("/mcp", headers={"Authorization": f"Bearer {token}"})

    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_entra_auth.py -v`
Expected: collection error `ImportError: No module named 'wingman_mcp.entra_auth'`.

- [ ] **Step 3: Implement EntraAuthMiddleware**

Create `src/wingman_mcp/entra_auth.py`:

```python
"""Entra ID JWT authentication middleware for the HTTP transport.

Sits in front of CredentialHeaderMiddleware. Validates `Authorization: Bearer`
tokens against a single configured Entra tenant. If a static access key is
configured AND no Authorization header was sent, falls back to the legacy
X-Wingman-Access-Key header. On success, stamps a Principal into the
_request_principal ContextVar.

See docs/superpowers/specs/2026-05-14-entra-id-auth-design.md.
"""
from __future__ import annotations

import hmac
import logging
from typing import Optional

import jwt
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from wingman_mcp.jwks import JWKSCache, JWKSUnavailable
from wingman_mcp.request_context import (
    Principal,
    _is_http_request,
    _request_principal,
)


log = logging.getLogger(__name__)

_REALM = 'Bearer realm="wingman-mcp"'


def _err(
    status: int,
    code: str,
    description: str,
    *,
    www_authenticate: Optional[str] = None,
):
    headers = {}
    if www_authenticate is not None:
        headers["WWW-Authenticate"] = www_authenticate
    return JSONResponse(
        {"error": code, "error_description": description},
        status_code=status,
        headers=headers,
    )


class EntraAuthMiddleware:
    """ASGI middleware that authenticates requests with Entra ID JWTs."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        tenant_id: Optional[str],
        audience: str = "api://wingman-mcp",
        required_scope: str = "mcp.access",
        static_access_key: Optional[str] = None,
        jwks_cache: Optional[JWKSCache] = None,
        clock_skew_seconds: int = 30,
    ) -> None:
        self._app = app
        self._tenant_id = tenant_id
        self._audience = audience
        self._required_scope = required_scope or ""
        self._static_access_key = static_access_key or None
        self._leeway = clock_skew_seconds
        if tenant_id:
            self._issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
            self._jwks = jwks_cache or JWKSCache(
                f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
            )
        else:
            self._issuer = None
            self._jwks = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path == "/health":
            await self._app(scope, receive, send)
            return

        headers: dict[bytes, bytes] = dict(scope["headers"])
        authz = headers.get(b"authorization", b"").decode("utf-8", errors="replace").strip()

        principal: Optional[Principal] = None

        if authz:
            principal_or_resp = await self._validate_bearer(authz, scope)
            if isinstance(principal_or_resp, Principal):
                principal = principal_or_resp
            else:
                # `_validate_bearer` returned an error response; short-circuit.
                await principal_or_resp(scope, receive, send)
                return
        else:
            principal_or_resp = self._validate_static_key(headers, scope)
            if isinstance(principal_or_resp, Principal):
                principal = principal_or_resp
            else:
                await principal_or_resp(scope, receive, send)
                return

        http_token = _is_http_request.set(True)
        principal_token = _request_principal.set(principal)
        try:
            await self._app(scope, receive, send)
        finally:
            _request_principal.reset(principal_token)
            _is_http_request.reset(http_token)

    async def _validate_bearer(self, authz: str, scope: Scope):
        if not authz.lower().startswith("bearer "):
            return _err(
                401,
                "invalid_request",
                "Authorization header must be 'Bearer <token>'",
                www_authenticate='Bearer error="invalid_request"',
            )
        if self._jwks is None or self._issuer is None or self._tenant_id is None:
            # Bearer token presented but JWT auth is not configured.
            return _err(
                401,
                "invalid_token",
                "Bearer tokens are not accepted by this server",
                www_authenticate='Bearer error="invalid_token"',
            )

        token = authz.split(" ", 1)[1].strip()

        try:
            unverified_header = jwt.get_unverified_header(token)
        except Exception as exc:
            log.warning("auth: unparseable JWT header: %s", exc)
            return _err(
                401,
                "invalid_token",
                "Token header could not be parsed",
                www_authenticate='Bearer error="invalid_token"',
            )

        kid = unverified_header.get("kid")
        if not kid:
            log.warning("auth: token missing kid header")
            return _err(
                401,
                "invalid_token",
                "Token header is missing 'kid'",
                www_authenticate='Bearer error="invalid_token"',
            )

        try:
            key = await self._jwks.get_key(kid)
        except JWKSUnavailable as exc:
            log.error("auth: JWKS unavailable: %s", exc)
            return _err(
                503,
                "auth_unavailable",
                "Authentication keys are temporarily unavailable",
            )

        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "aud", "tid", "oid"]},
                leeway=self._leeway,
            )
        except jwt.PyJWTError as exc:
            log.warning(
                "auth: token rejected (kid=%s aud=%s iss=%s): %s",
                kid,
                self._audience,
                self._issuer,
                exc,
            )
            return _err(
                401,
                "invalid_token",
                "Token failed validation",
                www_authenticate='Bearer error="invalid_token"',
            )

        if claims.get("tid") != self._tenant_id:
            log.warning(
                "auth: tid mismatch (token tid=%s expected=%s)",
                claims.get("tid"),
                self._tenant_id,
            )
            return _err(
                401,
                "invalid_token",
                "Token tenant does not match configured tenant",
                www_authenticate='Bearer error="invalid_token"',
            )

        if self._required_scope:
            scp = claims.get("scp", "") or ""
            scopes = scp.split(" ") if isinstance(scp, str) else []
            if self._required_scope not in scopes:
                log.warning(
                    "auth: missing required scope %s (got %r)",
                    self._required_scope,
                    scp,
                )
                return _err(
                    403,
                    "insufficient_scope",
                    f"Token is missing required scope '{self._required_scope}'",
                    www_authenticate=(
                        f'Bearer error="insufficient_scope", scope="{self._required_scope}"'
                    ),
                )

        return Principal(
            oid=claims.get("oid"),
            tid=claims.get("tid"),
            upn=claims.get("preferred_username") or claims.get("upn"),
            auth_method="entra",
        )

    def _validate_static_key(self, headers: dict[bytes, bytes], scope: Scope):
        if not self._static_access_key:
            return _err(
                401,
                "unauthorized",
                "Authentication required",
                www_authenticate=_REALM,
            )

        provided = headers.get(b"x-wingman-access-key", b"").decode(
            "utf-8", errors="replace"
        )
        if not hmac.compare_digest(provided, self._static_access_key):
            return _err(
                401,
                "unauthorized",
                "Authentication required",
                www_authenticate=_REALM,
            )

        return Principal(oid=None, tid=None, upn=None, auth_method="static_key")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_entra_auth.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/entra_auth.py tests/test_entra_auth.py
git commit -m "Add EntraAuthMiddleware with JWT validation and static-key fallback"
```

---

## Task 5: Remove static-key check from CredentialHeaderMiddleware

Now that `EntraAuthMiddleware` owns identity, `CredentialHeaderMiddleware` should only handle UEM headers. The `/health` bypass stays as defense in depth.

**Files:**
- Modify: `src/wingman_mcp/middleware.py`
- Modify (in spirit, add new test): `tests/test_credential_middleware.py` (new file)

- [ ] **Step 1: Write a failing test that verifies the middleware no longer gates on the access key**

Create `tests/test_credential_middleware.py`:

```python
"""Tests for CredentialHeaderMiddleware. After the Entra refactor this middleware
is only responsible for UEM credential extraction, never for access control."""
import os
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from wingman_mcp.middleware import CredentialHeaderMiddleware
from wingman_mcp.request_context import _request_credentials


def _build(monkeypatch, access_key_env: str | None):
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
    creds = captured["creds"]
    assert creds is not None
    assert creds.client_id == "cid"
    assert creds.api_base_url == "https://api"  # trailing slash stripped


def test_health_bypass_still_works(monkeypatch):
    mw, _ = _build(monkeypatch, access_key_env=None)
    client = TestClient(mw)

    r = client.get("/health")

    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify the first one fails**

Run: `.venv/bin/pytest tests/test_credential_middleware.py -v`
Expected: `test_no_access_key_header_passes_even_when_env_var_set` FAILs with 401 (the old behavior still rejects).

- [ ] **Step 3: Strip the static-key check from `middleware.py`**

Replace the entire contents of `src/wingman_mcp/middleware.py` with:

```python
"""ASGI middleware for HTTP server mode.

Extracts UEM credentials from request headers and stores them in
ContextVars so that MCP tool handlers can use them without any
server-side credential storage.

Headers consumed:
  X-UEM-Client-ID      OAuth client ID
  X-UEM-Client-Secret  OAuth client secret
  X-UEM-Token-URL      Token endpoint URL
  X-UEM-API-URL        UEM API base URL

Access control is handled upstream by EntraAuthMiddleware. The `/health`
path bypass is kept here as defense in depth so this middleware is still
safe if ever mounted alone (e.g. in a test).
"""
from starlette.types import ASGIApp, Receive, Scope, Send

from wingman_mcp.request_context import _is_http_request, _request_credentials


class CredentialHeaderMiddleware:
    """Starlette-compatible ASGI middleware that reads UEM credentials from headers."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if path == "/health":
            await self._app(scope, receive, send)
            return

        headers: dict[bytes, bytes] = dict(scope["headers"])

        client_id = headers.get(b"x-uem-client-id", b"").decode("utf-8", errors="replace").strip()
        client_secret = headers.get(b"x-uem-client-secret", b"").decode("utf-8", errors="replace").strip()
        token_url = headers.get(b"x-uem-token-url", b"").decode("utf-8", errors="replace").strip()
        api_base_url = headers.get(b"x-uem-api-url", b"").decode("utf-8", errors="replace").strip()

        creds = None
        if client_id and client_secret and token_url and api_base_url:
            from wingman_mcp.credentials import UEMCredentials
            creds = UEMCredentials(
                client_id=client_id,
                client_secret=client_secret,
                token_url=token_url,
                api_base_url=api_base_url.rstrip("/"),
            )

        http_token = _is_http_request.set(True)
        creds_token = _request_credentials.set(creds)
        try:
            await self._app(scope, receive, send)
        finally:
            _request_credentials.reset(creds_token)
            _is_http_request.reset(http_token)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_credential_middleware.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/middleware.py tests/test_credential_middleware.py
git commit -m "Drop static-key check from CredentialHeaderMiddleware (now in EntraAuthMiddleware)"
```

---

## Task 6: Wire middlewares into `run_http_server` + boot guard

**Files:**
- Modify: `src/wingman_mcp/server.py` (lines 1986-2042, plus a new helper function)
- Create: `tests/test_http_auth_integration.py`

- [ ] **Step 1: Write failing tests for the integration and boot guard**

Create `tests/test_http_auth_integration.py`:

```python
"""End-to-end test of the HTTP middleware stack: Entra auth in front of
credential extraction."""
import time
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import base64
import jwt
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from wingman_mcp.entra_auth import EntraAuthMiddleware
from wingman_mcp.jwks import JWKSCache
from wingman_mcp.middleware import CredentialHeaderMiddleware
from wingman_mcp.request_context import _request_credentials, _request_principal
from wingman_mcp.server import _validate_http_auth_config


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
    c = captured["creds"]
    assert c is not None and c.client_id == "cid"


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


class _Boom:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        raise AssertionError("must not hit network")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_http_auth_integration.py -v`
Expected: collection error or failures referencing missing `_validate_http_auth_config`.

- [ ] **Step 3: Add `_validate_http_auth_config` and wire middlewares**

Edit `src/wingman_mcp/server.py`. Find the `run_http_server` function (currently at line 1986). Replace the entire function (and add a new helper above it) with:

```python
def _validate_http_auth_config() -> None:
    """Refuse to start the HTTP server with no usable auth path.

    Either ENTRA_TENANT_ID (Entra JWT auth) or WINGMAN_MCP_ACCESS_KEY
    (static-key fallback) must be set; otherwise the server would be
    effectively open. Failing here is loud and at startup, not silent
    and at request time.
    """
    import os

    if not os.environ.get("ENTRA_TENANT_ID", "").strip() and not os.environ.get(
        "WINGMAN_MCP_ACCESS_KEY", ""
    ).strip():
        raise SystemExit(
            "Refusing to start HTTP server: neither ENTRA_TENANT_ID nor "
            "WINGMAN_MCP_ACCESS_KEY is set. Configure Entra ID authentication "
            "or set a static access key. See "
            "docs/superpowers/specs/2026-05-14-entra-id-auth-design.md."
        )


async def run_http_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the MCP server over Streamable HTTP for hosted/cloud deployments.

    Each user's UEM credentials are passed via request headers and are never
    stored server-side. Identity is verified by EntraAuthMiddleware against
    a single configured Entra tenant.

    Required dependencies: pip install 'wingman-mcp[cloud]'
    """
    import os

    _validate_http_auth_config()

    try:
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.responses import PlainTextResponse
        from starlette.types import Receive, Scope, Send
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            f"HTTP mode requires additional dependencies: {exc}\n"
            "Install with: pip install 'wingman-mcp[cloud]'"
        ) from exc

    from wingman_mcp.middleware import CredentialHeaderMiddleware
    from wingman_mcp.entra_auth import EntraAuthMiddleware

    session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=None,
        json_response=False,
        stateless=True,
    )

    class _App:
        """Minimal ASGI app: routes /health and /mcp."""

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "lifespan":
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                msg = await receive()
                if msg["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
            elif scope["type"] == "http":
                if scope["path"] == "/health":
                    resp = PlainTextResponse("ok")
                    await resp(scope, receive, send)
                else:
                    await session_manager.handle_request(scope, receive, send)

    tenant_id = os.environ.get("ENTRA_TENANT_ID", "").strip() or None
    audience = os.environ.get("ENTRA_AUDIENCE", "").strip() or "api://wingman-mcp"
    required_scope = os.environ.get("ENTRA_REQUIRED_SCOPE", "mcp.access").strip()
    static_access_key = os.environ.get("WINGMAN_MCP_ACCESS_KEY", "").strip() or None

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
    if static_access_key:
        print("Static access key fallback: ENABLED")

    config = uvicorn.Config(asgi_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    async with session_manager.run():
        await server.serve()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_http_auth_integration.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full test suite to confirm nothing else broke**

Run: `.venv/bin/pytest -q`
Expected: All previously passing tests still pass; the new files add ~25 new tests.

- [ ] **Step 6: Commit**

```bash
git add src/wingman_mcp/server.py tests/test_http_auth_integration.py
git commit -m "Mount EntraAuthMiddleware in run_http_server with boot-time auth-config guard"
```

---

## Task 7: README documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Locate the HTTP / cloud section in the README**

Run: `grep -n "HTTP\|cloud\|WINGMAN_MCP_ACCESS_KEY\|X-Wingman-Access-Key" README.md`
Read the surrounding lines to find the right insertion point. The new content should sit alongside whatever documents `WINGMAN_MCP_ACCESS_KEY` today (or alongside the cloud install instructions if there is no such section yet).

- [ ] **Step 2: Document the new env vars**

Add (or update) a subsection in `README.md`. Suggested heading and content:

```markdown
### HTTP authentication

When running `wingman-mcp` over HTTP (the `[cloud]` extra), every request must
either present a valid Entra ID access token or the static fallback key.

Environment variables:

| Var | Required | Default | Purpose |
|---|---|---|---|
| `ENTRA_TENANT_ID` | If using JWT auth | (none) | Single Entra tenant accepted by the server. |
| `ENTRA_AUDIENCE` | No | `api://wingman-mcp` | Expected `aud` claim of incoming tokens. |
| `ENTRA_REQUIRED_SCOPE` | No | `mcp.access` | Required scope in the `scp` claim. Set empty to skip. |
| `WINGMAN_MCP_ACCESS_KEY` | If JWT auth is not used | (none) | Enables the static-key fallback via the `X-Wingman-Access-Key` header. |

The server refuses to start if neither `ENTRA_TENANT_ID` nor
`WINGMAN_MCP_ACCESS_KEY` is set. See
`docs/superpowers/specs/2026-05-14-entra-id-auth-design.md` for the operator
setup checklist (Entra app registration, exposed scopes, manifest tweaks).

Clients authenticate with one of:

- `Authorization: Bearer <entra-access-token>` (preferred)
- `X-Wingman-Access-Key: <value>` (fallback, only if `WINGMAN_MCP_ACCESS_KEY` is set)

Per-user UEM credentials still travel in the `X-UEM-*` headers and are not
stored server-side.
```

If the README already has a "Cloud" or "HTTP" section, fold this content into it; if not, add it as a new top-level section above any existing config sections.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document Entra ID env vars in README"
```

---

## Final check

- [ ] **Step 1: Run the full test suite one more time**

Run: `.venv/bin/pytest -q`
Expected: All tests pass.

- [ ] **Step 2: Smoke-check the boot guard manually**

Run: `env -u ENTRA_TENANT_ID -u WINGMAN_MCP_ACCESS_KEY .venv/bin/python -c "from wingman_mcp.server import _validate_http_auth_config; _validate_http_auth_config()"`
Expected: `SystemExit` with the clear error message.

Run: `ENTRA_TENANT_ID=abc .venv/bin/python -c "from wingman_mcp.server import _validate_http_auth_config; _validate_http_auth_config()"`
Expected: exits cleanly.

- [ ] **Step 3: Confirm only intended files changed**

Run: `git log --oneline dev ^origin/dev`
Expected: roughly 6-7 commits, one per task.

Run: `git diff origin/dev..dev --stat`
Expected: the modified/created files listed in the "File Structure" section.

---

## Notes for the executing engineer

- TDD is non-optional here: write the test first, see it fail, then implement. The tests in this plan are deliberately complete so you can copy-paste them.
- Commit after each task. Memory says: never add `Co-Authored-By` lines on commits in this repo.
- Currently on branch `dev`. Do not switch to `main` or merge; the user squash-merges to `main` themselves.
- The static-key removal in Task 5 is intentionally a separate commit from the Entra middleware addition; this keeps each commit reversible.
- If `pytest-asyncio` warns about `asyncio_mode`, double-check the `[tool.pytest.ini_options]` block matches what Task 3 specifies.
- Do not introduce per-user UEM credential storage; that is explicitly out of scope (see the design doc's non-goals).
