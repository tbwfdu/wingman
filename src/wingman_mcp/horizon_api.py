"""Horizon Server REST API client and operation wrappers.

Auth: POST /rest/login with {username, domain, password: [string]} returns
an access_token (JWT, ~10 min lifetime) and a refresh_token.  Subsequent
calls send Authorization: Bearer <access_token>.  POST /rest/refresh
exchanges a refresh_token for a new access/refresh pair.

Per OpenAPI spec (Horizon 2603) — see
developer.omnissa.com/horizon-apis/horizon-server/versions/2603/rest-api-swagger-docs.json.
"""
from __future__ import annotations

import base64
import json as _json
import time
from typing import Any, Optional

import httpx

from wingman_mcp.api_client import ApiError, ProductApiClient


def _decode_jwt_exp(token: str) -> Optional[int]:
    """Pull `exp` out of a JWT without verifying the signature.

    Used to size the local cache; the server is the authority.  Returns
    seconds-from-now until expiry, or None if the token is not parseable.
    """
    try:
        payload = token.split(".")[1]
        # Pad to a multiple of 4 for urlsafe_b64decode.
        padded = payload + "=" * (-len(payload) % 4)
        data = _json.loads(base64.urlsafe_b64decode(padded.encode()))
        exp = int(data.get("exp", 0))
        if exp <= 0:
            return None
        return max(exp - int(time.time()), 0)
    except Exception:
        return None


class HorizonClient(ProductApiClient):
    """Bearer-token client for a Horizon Connection Server.

    server_url is the bare https://horizon.example.com — the client appends
    /rest itself so callers don't have to remember the suffix.
    """

    DEFAULT_TOKEN_TTL_SECONDS = 600  # 10 min, used when JWT has no exp

    def __init__(self, server_url: str, username: str, password: str,
                 domain: str, *, timeout: Optional[float] = None) -> None:
        # Normalize: strip trailing slash and any /rest the caller already added.
        base = server_url.rstrip("/")
        if base.endswith("/rest"):
            base = base[: -len("/rest")]
        super().__init__(base + "/rest", timeout=timeout)
        self._username = username
        self._password = password
        self._domain = domain
        self._refresh_token: Optional[str] = None

    def _post_json_raw(self, path: str, body: dict) -> httpx.Response:
        """POST without the auth-header path — used for login/refresh."""
        url = self._url(path)
        try:
            resp = httpx.post(
                url,
                json=body,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise ApiError(0, str(e), method="POST", url=url)
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text or "",
                           method="POST", url=url)
        return resp

    def _acquire_token(self) -> tuple[str, int]:
        # Prefer refresh-token rotation when available — avoids re-sending
        # the password and is the documented path.
        if self._refresh_token:
            try:
                resp = self._post_json_raw("/refresh",
                                           {"refresh_token": self._refresh_token})
                body = resp.json()
                access = body["access_token"]
                self._refresh_token = body.get("refresh_token", self._refresh_token)
                ttl = _decode_jwt_exp(access) or self.DEFAULT_TOKEN_TTL_SECONDS
                return access, ttl
            except ApiError:
                # Refresh failed (e.g. token expired) — fall through to full login.
                self._refresh_token = None

        resp = self._post_json_raw("/login", {
            "username": self._username,
            "domain": self._domain,
            # The spec types `password` as `array<string>` — use a single-item list.
            "password": [self._password],
        })
        body = resp.json()
        access = body["access_token"]
        self._refresh_token = body.get("refresh_token")
        ttl = _decode_jwt_exp(access) or self.DEFAULT_TOKEN_TTL_SECONDS
        return access, ttl


# ---------------------------------------------------------------------------
# Operation wrappers (one per MCP tool).
#
# All list endpoints accept the same pagination/filter/sort params:
# page, size, filter, sort_by, order_by.  We pass everything through.
# ---------------------------------------------------------------------------

def _list_params(kwargs: dict) -> Optional[dict]:
    params = {k: v for k, v in kwargs.items() if v is not None}
    return params or None


def search_desktop_pools(client: HorizonClient, **kwargs: Any) -> Any:
    """List desktop pools. Filters: page, size, filter, sort_by, order_by."""
    return client.get("/inventory/v1/desktop-pools", params=_list_params(kwargs))


def get_desktop_pool(client: HorizonClient, pool_id: str) -> Any:
    return client.get(f"/inventory/v1/desktop-pools/{pool_id}")


def search_farms(client: HorizonClient, **kwargs: Any) -> Any:
    """List farms (RDSH). Filters: page, size, filter, sort_by, order_by."""
    return client.get("/inventory/v1/farms", params=_list_params(kwargs))


def get_farm(client: HorizonClient, farm_id: str) -> Any:
    return client.get(f"/inventory/v1/farms/{farm_id}")


def search_machines(client: HorizonClient, **kwargs: Any) -> Any:
    """List machines (VMs). Filters: page, size, filter, sort_by, order_by."""
    return client.get("/inventory/v1/machines", params=_list_params(kwargs))


def get_machine(client: HorizonClient, machine_id: str) -> Any:
    return client.get(f"/inventory/v1/machines/{machine_id}")


def search_sessions(client: HorizonClient, **kwargs: Any) -> Any:
    """List user sessions (latest schema, v8)."""
    return client.get("/inventory/v8/sessions", params=_list_params(kwargs))


def get_session(client: HorizonClient, session_id: str) -> Any:
    return client.get(f"/inventory/v8/sessions/{session_id}")


def disconnect_sessions(client: HorizonClient, session_ids: list[str]) -> Any:
    """Disconnect the given user sessions (mutation).

    Per spec the request body is a bare JSON array of session IDs.
    """
    return client.post("/inventory/v1/sessions/action/disconnect",
                       body=[str(s) for s in session_ids])


def restart_machines(client: HorizonClient, machine_ids: list[str],
                     force_operation: bool = False) -> Any:
    """Restart (reboot) the given VMs (mutation).

    force_operation=True restarts machines even when sessions are open.
    """
    body = {
        "machineIds": [str(m) for m in machine_ids],
        "forceOperation": bool(force_operation),
    }
    return client.post("/inventory/v1/machines/action/restart", body=body)
