"""App Volumes Manager REST API client and operation wrappers.

App Volumes uses session-cookie authentication: POST /app_volumes/sessions
with a username and password returns a `_session_id` cookie which must be
sent on every subsequent request.  There is no Bearer token.

Per OpenAPI spec (App Volumes 2603) — see
developer.omnissa.com/app-volumes-apis/versions/2603/swagger.json.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from wingman_mcp.api_client import ApiError, DEFAULT_TIMEOUT, ProductApiClient


class AppVolumesClient(ProductApiClient):
    """Session-cookie-based client for an App Volumes Manager."""

    # Conservative session TTL in seconds; the server returns no expiry hint
    # so we re-login on 401.  15 minutes keeps the auth round-trip rare while
    # still bounding the lifetime of a stale cookie.
    SESSION_TTL_SECONDS = 15 * 60

    def __init__(self, manager_url: str, username: str, password: str,
                 *, timeout: Optional[float] = None) -> None:
        super().__init__(manager_url, timeout=timeout)
        self._username = username
        self._password = password

    # The base class stores `_token` and adds an Authorization header; for
    # App Volumes we instead carry a session cookie.  Override the headers
    # builder and the request path entirely.

    def _acquire_token(self) -> tuple[str, int]:
        """Log in and return (session_cookie_value, expires_in_seconds)."""
        url = f"{self.base_url}/app_volumes/sessions"
        try:
            resp = httpx.post(
                url,
                json={"username": self._username, "password": self._password},
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise ApiError(0, str(e), method="POST", url=url)
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text or "",
                           method="POST", url=url)
        # AV sets a `_session_id` cookie; fall back to the first cookie if
        # the name ever changes.
        cookie = resp.cookies.get("_session_id")
        if not cookie and resp.cookies:
            cookie = next(iter(resp.cookies.values()))
        if not cookie:
            raise ApiError(
                resp.status_code,
                "App Volumes did not return a session cookie",
                method="POST", url=url,
            )
        return cookie, self.SESSION_TTL_SECONDS

    def _auth_header_value(self, token: str) -> str:
        # Unused for App Volumes; auth is via Cookie.
        return ""

    def _headers(self, accept: Optional[str] = None) -> dict[str, str]:
        token = self.get_token()
        return {
            "Cookie": f"_session_id={token}",
            "Accept": accept or self.accept,
            "Content-Type": "application/json",
        }


# ---------------------------------------------------------------------------
# Operation wrappers (one per MCP tool).  Each takes a fresh-or-cached
# AppVolumesClient and returns the parsed JSON response.
# ---------------------------------------------------------------------------

def search_applications(client: AppVolumesClient, **kwargs: Any) -> dict:
    """Search Applications (top-level products that contain packages)."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return client.get("/app_volumes/app_products", params=params or None)


def get_application(client: AppVolumesClient, app_id: str) -> dict:
    """Get details of an Application by ID."""
    return client.get(f"/app_volumes/app_products/{app_id}")


def search_packages(client: AppVolumesClient, **kwargs: Any) -> dict:
    """Search Packages (the deliverable virtual disks)."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return client.get("/app_volumes/app_packages", params=params or None)


def get_package(client: AppVolumesClient, package_id: str) -> dict:
    """Get details of a Package by ID."""
    return client.get(f"/app_volumes/app_packages/{package_id}")


def search_writable_volumes(client: AppVolumesClient, **kwargs: Any) -> dict:
    """Search Writable Volumes.

    Filters: volume_guid, user_guid, owner_name, created_after,
    updated_after, min_capacity, max_capacity, count.
    """
    params = {k: v for k, v in kwargs.items() if v is not None}
    return client.get("/app_volumes/writables", params=params or None)


def get_writable_volume(client: AppVolumesClient, writable_id: str) -> dict:
    """Get a Writable Volume by ID."""
    return client.get(f"/app_volumes/writables/{writable_id}")


def grow_writable_volume(client: AppVolumesClient, writable_ids: list[int],
                         size_mb: int) -> dict:
    """Grow one or more Writable Volumes to a new size (MB).

    Mutation — chosen as the Phase 1 mutation because it is non-destructive
    and a common admin task (users running out of profile space).
    Per the AV 2603 OpenAPI spec the body shape is {volumes, size_mb}.
    """
    body = {
        "volumes": [int(v) for v in writable_ids],
        "size_mb": int(size_mb),
    }
    return client.post("/app_volumes/writables/grow", body=body)
