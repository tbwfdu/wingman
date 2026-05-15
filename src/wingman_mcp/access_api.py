"""Workspace ONE Access REST API client and operation wrappers.

Auth: client-credentials OAuth on a per-tenant URL.
POST <tenant_url>/SAAS/auth/oauthtoken with HTTP Basic auth
(client_id : client_secret) and `grant_type=client_credentials` (query
parameter — Access supports it both as query and form, query is what the
spec documents) returns {access_token, expires_in, ...}.  Subsequent calls
use Authorization: Bearer <access_token>.

Per OpenAPI spec — see developer.omnissa.com/omnissa-access-apis/openapi.json.
"""
from __future__ import annotations

import base64
from typing import Any, Optional

import httpx

from wingman_mcp.api_client import ApiError, ProductApiClient


def _normalize_tenant(tenant_url: str) -> str:
    url = tenant_url.strip().rstrip("/")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


_SCIM_BASE = "/SAAS/jersey/manager/api/scim"
_REPORT_BASE = "/SAAS/jersey/manager/api/reporting/reports"
_ENTITLEMENTS_SEARCH = "/SAAS/jersey/manager/api/entitlements/search"
_DEFAULT_TOKEN_PATH = "/SAAS/auth/oauthtoken"


class AccessClient(ProductApiClient):
    """Bearer-token client for a Workspace ONE Access tenant."""

    def __init__(self, tenant_url: str, client_id: str, client_secret: str,
                 *, token_url: Optional[str] = None,
                 timeout: Optional[float] = None) -> None:
        super().__init__(_normalize_tenant(tenant_url), timeout=timeout)
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url or f"{self.base_url}{_DEFAULT_TOKEN_PATH}"

    def _acquire_token(self) -> tuple[str, int]:
        basic = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        try:
            resp = httpx.post(
                self._token_url,
                params={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {basic}",
                    "Accept": "application/json",
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise ApiError(0, str(e), method="POST", url=self._token_url)
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text or "",
                           method="POST", url=self._token_url)
        body = resp.json()
        token = body.get("access_token")
        if not token:
            raise ApiError(resp.status_code,
                           "Access returned no access_token",
                           method="POST", url=self._token_url)
        expires_in = int(body.get("expires_in", 3600))
        return token, expires_in


# ---------------------------------------------------------------------------
# Operation wrappers
# ---------------------------------------------------------------------------

def _list_params(kwargs: dict) -> Optional[dict]:
    params = {k: v for k, v in kwargs.items() if v is not None}
    return params or None


def search_users(client: AccessClient, **kwargs: Any) -> Any:
    """Search SCIM users in an Access tenant.

    Same vocabulary as Identity Service: filter, startIndex, count,
    sortBy, sortOrder, attributes, customSchemaExtensionTypes.
    """
    return client.get(f"{_SCIM_BASE}/Users", params=_list_params(kwargs))


def get_user(client: AccessClient, user_id: str,
             attributes: Optional[str] = None,
             directoryUuid: Optional[str] = None) -> Any:
    params = _list_params({
        "attributes": attributes,
        "directoryUuid": directoryUuid,
    })
    return client.get(f"{_SCIM_BASE}/Users/{user_id}", params=params)


def search_groups(client: AccessClient, **kwargs: Any) -> Any:
    return client.get(f"{_SCIM_BASE}/Groups", params=_list_params(kwargs))


def get_group(client: AccessClient, group_id: str,
              attributes: Optional[str] = None) -> Any:
    params = _list_params({"attributes": attributes})
    return client.get(f"{_SCIM_BASE}/Groups/{group_id}", params=params)


def search_entitlements(client: AccessClient, *,
                        userId: Optional[str] = None,
                        showVisibleAppsOnly: Optional[bool] = None,
                        startIndex: Optional[int] = None,
                        pageSize: Optional[int] = None,
                        criteria: Optional[dict] = None) -> Any:
    """Search entitlements (catalog items) for a user or the authenticated client.

    The body is a SearchCriteria object — pass {} for "all entitlements"
    or a filter spec to narrow it.
    """
    params = _list_params({
        "userId": userId,
        "showVisibleAppsOnly": showVisibleAppsOnly,
        "startIndex": startIndex,
        "pageSize": pageSize,
    })
    return client.post(_ENTITLEMENTS_SEARCH, body=criteria or {}, params=params)


def get_activity_summary_report(client: AccessClient, interval: str) -> Any:
    """Get the activity summary report for a time interval.

    interval is one of the values Access accepts (e.g. 'day', 'week',
    'month').  Refer to search_api_reference for the exact vocabulary
    of your tenant version.
    """
    return client.get(f"{_REPORT_BASE}/activity/reportstable",
                      params={"interval": interval})


def create_user(client: AccessClient, user_resource: dict, *,
                sendMail: Optional[bool] = None,
                attributes: Optional[str] = None) -> Any:
    """Create a local user in an Access tenant (mutation).

    user_resource follows the SdkUserResource schema — include `userName`,
    `name`, `emails`, and optional `password`.  When sendMail is true the
    user receives an email to set their password.
    """
    params = _list_params({"sendMail": sendMail, "attributes": attributes})
    return client.post(f"{_SCIM_BASE}/Users",
                       body=user_resource, params=params)
