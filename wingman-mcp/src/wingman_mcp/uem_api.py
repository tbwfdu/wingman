"""Workspace ONE UEM REST API client functions.

Each function takes a UEMAuth instance and query parameters,
makes an authenticated API call, and returns the parsed response.
"""
from typing import Any, Optional

import httpx

from wingman_mcp.auth import UEMAuth

ACCEPT_V1 = "application/json;version=1"
ACCEPT_V2 = "application/json;version=2"
ACCEPT_V3 = "application/json;version=3"
TIMEOUT = 20.0


def _headers(auth: UEMAuth, accept: str = ACCEPT_V2) -> dict:
    return {
        "Authorization": f"Bearer {auth.get_token()}",
        "Accept": accept,
        "Content-Type": "application/json",
    }


def _get(auth: UEMAuth, path: str, params: Optional[dict] = None,
         accept: str = ACCEPT_V2) -> Any:
    """Perform an authenticated GET request against the UEM API."""
    url = f"{auth.api_base_url}{path}"
    resp = httpx.get(url, headers=_headers(auth, accept), params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _post(auth: UEMAuth, path: str, body: Optional[dict] = None,
          accept: str = ACCEPT_V2) -> Any:
    """Perform an authenticated POST request against the UEM API."""
    url = f"{auth.api_base_url}{path}"
    resp = httpx.post(url, headers=_headers(auth, accept), json=body, timeout=TIMEOUT)
    resp.raise_for_status()
    if resp.status_code == 204 or not resp.content:
        return {"status": "success", "http_status": resp.status_code}
    return resp.json()


# ---------------------------------------------------------------------------
# Device operations
# ---------------------------------------------------------------------------

def search_devices(auth: UEMAuth, **kwargs) -> dict:
    """Search for devices. Supports filters: user, model, platform,
    lastseen, ownership, lgid (OG id), compliantstatus, seensince, etc."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return _get(auth, "/api/mdm/devices/search", params=params)


def get_device(auth: UEMAuth, device_id: str) -> dict:
    """Get device details by device ID."""
    return _get(auth, f"/api/mdm/devices/{device_id}")


def get_device_by_uuid(auth: UEMAuth, device_uuid: str) -> dict:
    """Get device details by device UUID."""
    return _get(auth, f"/api/mdm/devices/{device_uuid}", accept=ACCEPT_V3)


def get_device_profiles(auth: UEMAuth, device_id: str, **kwargs) -> dict:
    """Get profiles installed on a device."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return _get(auth, f"/api/mdm/devices/{device_id}/profiles", params=params, accept=ACCEPT_V1)


def get_device_apps(auth: UEMAuth, device_id: str, **kwargs) -> dict:
    """Get apps installed on a device."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return _get(auth, f"/api/mdm/devices/{device_id}/apps", params=params, accept=ACCEPT_V1)


def get_device_security(auth: UEMAuth, device_id: str) -> dict:
    """Get security info for a device."""
    return _get(auth, f"/api/mdm/devices/{device_id}/security", accept=ACCEPT_V1)


def get_device_network(auth: UEMAuth, device_id: str) -> dict:
    """Get network info for a device."""
    return _get(auth, f"/api/mdm/devices/{device_id}/network", accept=ACCEPT_V1)


def send_device_command(auth: UEMAuth, device_id: str, command: str) -> dict:
    """Send a command to a device (e.g. Lock, EnterpriseWipe, DeviceQuery, SyncDevice)."""
    return _post(auth, f"/api/mdm/devices/{device_id}/commands?command={command}",
                 accept=ACCEPT_V1)


# ---------------------------------------------------------------------------
# Organization Group operations
# ---------------------------------------------------------------------------

def search_organization_groups(auth: UEMAuth, **kwargs) -> dict:
    """Search organization groups. Supports: name, groupid, orderby, page, pagesize."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return _get(auth, "/api/system/groups/search", params=params, accept=ACCEPT_V1)


def get_organization_group(auth: UEMAuth, og_id: str) -> dict:
    """Get details of an organization group by its ID."""
    return _get(auth, f"/api/system/groups/{og_id}", accept=ACCEPT_V1)


def get_og_children(auth: UEMAuth, og_id: str) -> dict:
    """Get child organization groups."""
    return _get(auth, f"/api/system/groups/{og_id}/children", accept=ACCEPT_V1)


# ---------------------------------------------------------------------------
# User operations
# ---------------------------------------------------------------------------

def search_users(auth: UEMAuth, **kwargs) -> dict:
    """Search enrollment users. Supports: firstname, lastname, email,
    locationgroupid, role, username, page, pagesize, orderby."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return _get(auth, "/api/system/users/search", params=params, accept=ACCEPT_V1)


def get_user(auth: UEMAuth, user_id: str) -> dict:
    """Get enrollment user details by user ID."""
    return _get(auth, f"/api/system/users/{user_id}", accept=ACCEPT_V1)


# ---------------------------------------------------------------------------
# Smart Group operations
# ---------------------------------------------------------------------------

def search_smart_groups(auth: UEMAuth, **kwargs) -> dict:
    """Search smart groups. Supports: name, organizationgroupid, orderby, page, pagesize."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return _get(auth, "/api/mdm/smartgroups/search", params=params, accept=ACCEPT_V1)


def get_smart_group(auth: UEMAuth, smart_group_id: str) -> dict:
    """Get smart group details by ID."""
    return _get(auth, f"/api/mdm/smartgroups/{smart_group_id}", accept=ACCEPT_V1)


# ---------------------------------------------------------------------------
# Profile operations
# ---------------------------------------------------------------------------

def search_profiles(auth: UEMAuth, **kwargs) -> dict:
    """Search device profiles. Supports: searchtext, type, platform,
    status, organizationgroupid, orderby, page, pagesize."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return _get(auth, "/api/mdm/profiles/search", params=params, accept=ACCEPT_V1)


# ---------------------------------------------------------------------------
# App operations
# ---------------------------------------------------------------------------

def search_apps(auth: UEMAuth, **kwargs) -> dict:
    """Search applications. Supports: type (internal/public/purchased),
    applicationname, bundleid, platform, model, status,
    locationgroupid, orderby, page, pagesize."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return _get(auth, "/api/mam/apps/search", params=params, accept=ACCEPT_V1)
