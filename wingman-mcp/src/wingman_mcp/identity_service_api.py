"""Omnissa Identity Service REST API client and operation wrappers.

Auth: client-credentials OAuth.  POST /acs/token with HTTP Basic auth
(client_id : client_secret) and form body `grant_type=client_credentials`
returns {access_token, expires_in, ...}.  Subsequent calls use
Authorization: Bearer <access_token>.

Per OpenAPI spec — see
developer.omnissa.com/omnissa-identity-service-api/omnissa-identity-service-api-doc.json.
"""
from __future__ import annotations

import base64
from typing import Any, Optional

import httpx

from wingman_mcp.api_client import ApiError, ProductApiClient


def _normalize_tenant(tenant_url: str) -> str:
    """Strip trailing slash on tenant URL.  Accepts with or without scheme."""
    url = tenant_url.strip().rstrip("/")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


class IdentityServiceClient(ProductApiClient):
    """Bearer-token client for an Omnissa Identity Service tenant.

    tenant_url is the base URL for the tenant (e.g. https://acme.example.com).
    All API paths are relative to that root.

    token_url, when supplied, overrides the default /acs/token endpoint —
    needed if the tenant front-doors auth at a different host than the
    SCIM API.  Defaults to <tenant_url>/acs/token.
    """

    def __init__(self, tenant_url: str, client_id: str, client_secret: str,
                 *, token_url: Optional[str] = None,
                 timeout: Optional[float] = None) -> None:
        super().__init__(_normalize_tenant(tenant_url), timeout=timeout)
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url or f"{self.base_url}/acs/token"

    def _acquire_token(self) -> tuple[str, int]:
        basic = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        try:
            resp = httpx.post(
                self._token_url,
                data={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {basic}",
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
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
                           "Identity Service returned no access_token",
                           method="POST", url=self._token_url)
        # Identity Service tokens default to ~1h; if absent, assume 3600.
        expires_in = int(body.get("expires_in", 3600))
        return token, expires_in


# ---------------------------------------------------------------------------
# Operation wrappers (one per MCP tool)
# ---------------------------------------------------------------------------

_SCIM_ACCEPT = "application/scim+json"


def _list_params(kwargs: dict) -> Optional[dict]:
    params = {k: v for k, v in kwargs.items() if v is not None}
    return params or None


def search_users(client: IdentityServiceClient, **kwargs: Any) -> Any:
    """Search SCIM users.

    SCIM filter syntax:  filter='userName eq "alice@example.com"'
    Pagination:          startIndex (1-based), count
    Sort:                sortBy, sortOrder (ascending|descending)
    Projection:          attributes, excludedAttributes (comma lists)
    """
    return client.get("/usergroup/scim/v2/Users",
                      params=_list_params(kwargs), accept=_SCIM_ACCEPT)


def get_user(client: IdentityServiceClient, user_id: str,
             attributes: Optional[str] = None,
             excludedAttributes: Optional[str] = None) -> Any:
    params = _list_params({
        "attributes": attributes,
        "excludedAttributes": excludedAttributes,
    })
    return client.get(f"/usergroup/scim/v2/Users/{user_id}",
                      params=params, accept=_SCIM_ACCEPT)


def search_groups(client: IdentityServiceClient, **kwargs: Any) -> Any:
    """Search SCIM groups (same filter/paging vocabulary as Users)."""
    return client.get("/usergroup/scim/v2/Groups",
                      params=_list_params(kwargs), accept=_SCIM_ACCEPT)


def get_group(client: IdentityServiceClient, group_id: str,
              attributes: Optional[str] = None,
              excludedAttributes: Optional[str] = None) -> Any:
    params = _list_params({
        "attributes": attributes,
        "excludedAttributes": excludedAttributes,
    })
    return client.get(f"/usergroup/scim/v2/Groups/{group_id}",
                      params=params, accept=_SCIM_ACCEPT)


def search_directories(client: IdentityServiceClient) -> Any:
    """List directories configured for the tenant."""
    return client.get("/usergroup/broker/directories")


def get_directory(client: IdentityServiceClient, directory_id: str) -> Any:
    return client.get(f"/usergroup/broker/directories/{directory_id}")


def create_user(client: IdentityServiceClient, user_resource: dict) -> Any:
    """Create a new SCIM user (mutation).

    user_resource is a SCIM 2.0 User payload, e.g.:
      {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": "alice@example.com",
        "name": {"givenName": "Alice", "familyName": "Smith"},
        "emails": [{"value": "alice@example.com", "primary": True}],
      }
    """
    return client.post("/usergroup/scim/v2/Users",
                       body=user_resource, accept=_SCIM_ACCEPT)
