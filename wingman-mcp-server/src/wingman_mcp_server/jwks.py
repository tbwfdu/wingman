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
