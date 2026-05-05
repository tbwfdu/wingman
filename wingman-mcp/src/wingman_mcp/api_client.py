"""Shared HTTP base for product API clients (Horizon, App Volumes, Access, …).

UEM keeps its own client (uem_api.py + auth.py) — this base is for the
non-UEM products added in the multi-product API rollout.

Subclasses provide token acquisition logic; the base handles caching,
auto-refresh ~60 seconds before expiry, and consistent error surfacing.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx


# Default request timeout (matches the non-docs HTTP timeout bumped in 7675414).
DEFAULT_TIMEOUT = 30.0


class ApiError(RuntimeError):
    """Raised when a product API call returns a non-2xx response.

    Carries the status code and a truncated body so the caller can surface
    a useful diagnostic without leaking large response payloads.
    """
    def __init__(self, status_code: int, body: str, *, method: str, url: str):
        self.status_code = status_code
        self.body = body
        self.method = method
        self.url = url
        super().__init__(
            f"{method} {url} → HTTP {status_code}: {body[:500]}"
        )


class ProductApiClient:
    """Base class for per-product REST clients.

    Subclass and implement `_acquire_token()` returning (token, expires_in_s).
    Override `_auth_header_value()` if the product uses a non-Bearer scheme.
    The base provides token caching, automatic refresh, and uniform request
    helpers.
    """

    accept: str = "application/json"
    timeout: float = DEFAULT_TIMEOUT

    def __init__(self, base_url: str, *, timeout: Optional[float] = None) -> None:
        self.base_url = base_url.rstrip("/")
        if timeout is not None:
            self.timeout = timeout
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    # -- token lifecycle ----------------------------------------------------

    def _acquire_token(self) -> tuple[str, int]:
        """Fetch a fresh token. Return (token_string, expires_in_seconds).

        Subclasses must implement.  Raise ApiError on auth failure.
        """
        raise NotImplementedError

    def _auth_header_value(self, token: str) -> str:
        """Build the Authorization header value.  Default: Bearer."""
        return f"Bearer {token}"

    def get_token(self, *, force_refresh: bool = False) -> str:
        """Return a valid token, refreshing if expired or forced."""
        if not force_refresh and self._token and time.time() < self._expires_at:
            return self._token
        token, expires_in = self._acquire_token()
        self._token = token
        # Refresh 60s early so we don't hand out about-to-expire tokens.
        self._expires_at = time.time() + max(int(expires_in) - 60, 0)
        return self._token

    def invalidate_token(self) -> None:
        """Drop the cached token; next call will re-acquire."""
        self._token = None
        self._expires_at = 0.0

    # -- request helpers ----------------------------------------------------

    def _headers(self, accept: Optional[str] = None) -> dict[str, str]:
        return {
            "Authorization": self._auth_header_value(self.get_token()),
            "Accept": accept or self.accept,
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[Any] = None,
        accept: Optional[str] = None,
    ) -> Any:
        url = self._url(path)
        headers = self._headers(accept)
        # Single retry on 401 in case the token expired between the cache
        # check and the request landing on the server.
        for attempt in (0, 1):
            resp = httpx.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=self.timeout,
            )
            if resp.status_code == 401 and attempt == 0:
                self.invalidate_token()
                headers = self._headers(accept)
                continue
            break
        if resp.status_code >= 400:
            raise ApiError(
                resp.status_code,
                resp.text or "",
                method=method,
                url=url,
            )
        if resp.status_code == 204 or not resp.content:
            return {"status": "success", "http_status": resp.status_code}
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            return resp.json()
        return resp.text

    def get(self, path: str, *, params: Optional[dict] = None,
            accept: Optional[str] = None) -> Any:
        return self._request("GET", path, params=params, accept=accept)

    def post(self, path: str, *, body: Optional[Any] = None,
             params: Optional[dict] = None, accept: Optional[str] = None) -> Any:
        return self._request("POST", path, params=params, json_body=body, accept=accept)

    def put(self, path: str, *, body: Optional[Any] = None,
            params: Optional[dict] = None, accept: Optional[str] = None) -> Any:
        return self._request("PUT", path, params=params, json_body=body, accept=accept)

    def patch(self, path: str, *, body: Optional[Any] = None,
              params: Optional[dict] = None, accept: Optional[str] = None) -> Any:
        return self._request("PATCH", path, params=params, json_body=body, accept=accept)

    def delete(self, path: str, *, params: Optional[dict] = None,
               accept: Optional[str] = None) -> Any:
        return self._request("DELETE", path, params=params, accept=accept)

    # -- diagnostic ---------------------------------------------------------

    def test_connection(self) -> dict:
        """Try acquiring a token and report the result."""
        try:
            self.get_token(force_refresh=True)
            return {
                "success": True,
                "base_url": self.base_url,
                "expires_in": int(self._expires_at - time.time()),
            }
        except ApiError as e:
            return {
                "success": False,
                "error": f"HTTP {e.status_code}: {e.body[:200]}",
                "base_url": self.base_url,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "base_url": self.base_url,
            }
