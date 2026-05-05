"""Horizon Cloud Service (Next-Gen) REST API client and operation wrappers.

Auth: client-credentials OAuth.  POST /auth/v1/oauth/token with HTTP Basic
auth (client_id : client_secret) and form body grant_type=client_credentials
returns {access_token, token_type='bearer', expires_in}.  Subsequent calls
use Authorization: Bearer <access_token>.

Almost every list/get endpoint requires `org_id` as a query parameter
(the CSP organization the tenant belongs to); the client auto-injects it
on every request so callers never have to remember.

Per OpenAPI spec — see
developer.omnissa.com/horizon-apis/horizon-cloud-nextgen/horizon-cloud-nextgen-api-doc-public.yaml.

Phase 5 deliberately ships read-only — Horizon Cloud's mutation surface
(performAction_v2, batchPerformVirtualMachineAction, deployment lifecycle)
has too many footguns to bundle into the initial rollout.
"""
from __future__ import annotations

import base64
from typing import Any, Optional

import httpx

from wingman_mcp.api_client import ApiError, ProductApiClient


def _normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


class HorizonCloudClient(ProductApiClient):
    """Bearer-token client for Horizon Cloud Service (Next-Gen).

    api_base_url is the regional cloud URL — typically one of:
        https://cloud-sg.horizon.omnissa.com
        https://cloud-us-2.horizon.omnissa.com
        ...etc.

    org_id (CSP organization ID) is auto-attached as a query parameter on
    every request, so callers don't need to repeat it on each tool call.
    """

    def __init__(self, api_base_url: str, client_id: str, client_secret: str,
                 org_id: str, *, timeout: Optional[float] = None) -> None:
        super().__init__(_normalize_url(api_base_url), timeout=timeout)
        self._client_id = client_id
        self._client_secret = client_secret
        self._org_id = org_id

    @property
    def org_id(self) -> str:
        return self._org_id

    def _acquire_token(self) -> tuple[str, int]:
        url = f"{self.base_url}/auth/v1/oauth/token"
        basic = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        try:
            resp = httpx.post(
                url,
                data={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {basic}",
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise ApiError(0, str(e), method="POST", url=url)
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, resp.text or "",
                           method="POST", url=url)
        body = resp.json()
        token = body.get("access_token")
        if not token:
            raise ApiError(resp.status_code,
                           "Horizon Cloud returned no access_token",
                           method="POST", url=url)
        expires_in = int(body.get("expires_in", 17999))
        return token, expires_in

    # Inject org_id on every request so callers never have to.
    def _request(self, method: str, path: str, *,
                 params: Optional[dict] = None,
                 json_body: Optional[Any] = None,
                 accept: Optional[str] = None) -> Any:
        merged = dict(params or {})
        merged.setdefault("org_id", self._org_id)
        return super()._request(method, path, params=merged,
                                json_body=json_body, accept=accept)


# ---------------------------------------------------------------------------
# Operation wrappers (read-only)
# ---------------------------------------------------------------------------

def _list_params(kwargs: dict) -> Optional[dict]:
    params = {k: v for k, v in kwargs.items() if v is not None}
    return params or None


def search_pools(client: HorizonCloudClient, **kwargs: Any) -> Any:
    """Get all pool groups (Horizon Cloud terminology for desktop pools).

    Filters: page, size, sort, search,
             sort_by_used_sessions, sort_by_consumed_sessions,
             include_internal_pools, exclude_disabled_pools,
             include_deleting_pools.
    """
    return client.get("/portal/v4/pools", params=_list_params(kwargs))


def get_pool(client: HorizonCloudClient, pool_id: str) -> Any:
    return client.get(f"/portal/v4/pools/{pool_id}")


def search_templates(client: HorizonCloudClient, **kwargs: Any) -> Any:
    """Get all templates (golden images / VM template specs).

    Filters: brokerable_only, expanded, page, size, sort,
             reported_search, template_search.
    """
    return client.get("/admin/v2/templates", params=_list_params(kwargs))


def get_template(client: HorizonCloudClient, template_id: str,
                 expanded: Optional[bool] = None) -> Any:
    return client.get(f"/admin/v2/templates/{template_id}",
                      params=_list_params({"expanded": expanded}))


def search_sessions(client: HorizonCloudClient,
                    userId: Optional[str] = None,
                    excludeAssigned: Optional[bool] = None) -> Any:
    """Filter active user sessions across all pools."""
    return client.get("/portal/v2/sessions",
                      params=_list_params({"userId": userId,
                                           "excludeAssigned": excludeAssigned}))


def search_edge_deployments(client: HorizonCloudClient, **kwargs: Any) -> Any:
    """List Edge deployments (the per-site connector / control plane).

    Filters: page, size, sort, search, include_reported_status.
    """
    return client.get("/admin/v2/edge-deployments", params=_list_params(kwargs))


def get_edge_deployment(client: HorizonCloudClient, edge_id: str,
                        include_reported_status: Optional[bool] = None) -> Any:
    return client.get(f"/admin/v2/edge-deployments/{edge_id}",
                      params=_list_params({"include_reported_status":
                                           include_reported_status}))


def search_active_directories(client: HorizonCloudClient, **kwargs: Any) -> Any:
    """List configured Active Directory / domain integrations.

    Filters: expanded, page, size, sort, search.
    """
    return client.get("/admin/v2/active-directories", params=_list_params(kwargs))


def search_uag_deployments(client: HorizonCloudClient, **kwargs: Any) -> Any:
    """List Unified Access Gateway deployments associated with the tenant.

    Filters: page, size, sort, search.
    """
    return client.get("/admin/v2/uag-deployments", params=_list_params(kwargs))


def search_sso_configurations(client: HorizonCloudClient, **kwargs: Any) -> Any:
    """List SSO / identity-provider configurations.

    Filters: expanded, page, size, sort, search.
    """
    return client.get("/admin/v2/sso-configurations", params=_list_params(kwargs))
