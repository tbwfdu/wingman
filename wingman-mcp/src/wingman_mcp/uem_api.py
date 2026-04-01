"""Workspace ONE UEM REST API client functions.

Each function takes a UEMAuth instance and query parameters,
makes an authenticated API call, and returns the parsed response.
"""
import base64
from typing import Any, Optional

import httpx

from wingman_mcp.auth import UEMAuth

ACCEPT_V1 = "application/json;version=1"
ACCEPT_V2 = "application/json;version=2"
ACCEPT_V3 = "application/json;version=3"
TIMEOUT = 20.0

# Map friendly platform names to API enum values
_PLATFORM_MAP = {
    "macos": "APPLE_OSX",
    "apple_osx": "APPLE_OSX",
    "windows": "WIN_RT",
    "win_rt": "WIN_RT",
    "linux": "LINUX",
}


def _normalize_platform(platform: str) -> str:
    """Convert a user-friendly platform name to the API enum value."""
    return _PLATFORM_MAP.get(platform.lower(), platform)


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
    if resp.status_code >= 400:
        detail = resp.text[:500] if resp.text else ""
        raise httpx.HTTPStatusError(
            f"{resp.status_code} {resp.reason_phrase}: {detail}",
            request=resp.request,
            response=resp,
        )
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
    return _get(auth, "/api/mdm/profiles/search", params=params, accept=ACCEPT_V2)


_PROFILE_PLATFORM_PATHS = {
    "winrt": "winrt",
    "apple": "apple",
    "appleosx": "apple",
    "android": "android",
}


def create_profile(auth: UEMAuth, platform: str, profile_json: str) -> dict:
    """Create a device profile from a V2 JSON body.

    Accepts the same General + payload schema returned by get_profile when
    V2 is supported.  Works for:
      - WinRT  — all payload types
      - Apple  — V2-supported payloads (Custom Settings, WiFi, VPN, SCEP,
                 Credentials, SSO Extension, Email, WebClips).
                 Profiles with non-V2 payloads (Dock, Disk Encryption, etc.)
                 cannot be created via this endpoint.
      - Android — standard V2 payloads

    Platform: WinRT, Apple, AppleOsX, or Android.
    """
    key = platform.lower()
    path_segment = _PROFILE_PLATFORM_PATHS.get(key)
    if not path_segment:
        raise ValueError(
            f"Unsupported platform '{platform}'. "
            f"Use one of: WinRT, Apple, AppleOsX, Android"
        )
    import json as _json
    body = _json.loads(profile_json) if isinstance(profile_json, str) else profile_json
    return _post(auth, f"/api/mdm/profiles/platforms/{path_segment}/create",
                 body=body, accept=ACCEPT_V2)


def get_profile(auth: UEMAuth, profile_id: str) -> dict:
    """Get full device profile details by profile ID.

    V2 is tried first and returns a General + payload-sections structure
    that can be round-tripped with create_profile.  V2 works for all
    Windows profiles and macOS/Android profiles whose payloads are in the
    V2 schema (Custom Settings, WiFi, VPN, SCEP, etc.).

    When V2 fails (non-V2 payloads like Dock or Disk Encryption), falls
    back to the metadata-transforms endpoint which returns full payload
    field values and profile metadata.  This data is read-only — there is
    no corresponding create/POST endpoint for it.
    """
    try:
        return _get(auth, f"/api/mdm/profiles/{profile_id}", accept=ACCEPT_V2)
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 400:
            raise
    # V2 unsupported for this profile — resolve UUIDs via search
    search = _get(auth, "/api/mdm/profiles/search",
                  params={"searchtext": "", "pagesize": 500}, accept=ACCEPT_V2)
    profile_uuid = None
    og_uuid = None
    for p in search.get("ProfileList", []):
        if str(p.get("ProfileId")) == str(profile_id):
            profile_uuid = p.get("ProfileUuid")
            og_uuid = p.get("OrganizationGroupUuid")
            break
    if not profile_uuid or not og_uuid:
        raise ValueError(f"Profile {profile_id} not found in search results")
    return _get(
        auth,
        f"/api/mdm/profiles/metadata-transforms/{og_uuid}/{profile_uuid}",
        params={
            "culture": "en-US",
            "context": "User",
            "management_type": "IMPERATIVE",
            "resource_type": "PROFILES",
        },
        accept=ACCEPT_V1,
    )


# ---------------------------------------------------------------------------
# App operations
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Compliance Policy operations
# ---------------------------------------------------------------------------

def search_compliance_policies(auth: UEMAuth, **kwargs) -> dict:
    """Search compliance policies. Supports: organizationgroupid, page, pagesize."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    url = f"{auth.api_base_url}/api/mdm/compliancepolicies"
    resp = httpx.get(url, headers=_headers(auth, ACCEPT_V1), params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    if resp.status_code == 204 or not resp.content:
        return {"CompliancePolicies": [], "Total": 0}
    return resp.json()


# ---------------------------------------------------------------------------
# Security Baseline operations
# ---------------------------------------------------------------------------

def get_baseline_templates(auth: UEMAuth) -> list:
    """List vendor baseline templates (MSFT, CIS) with available OS versions."""
    return _get(auth, "/api/mdm/baselines/templates", accept=ACCEPT_V1)


def search_baseline_policies(auth: UEMAuth, os_version_uuid: str, **kwargs) -> dict:
    """List GPO policies in a baseline catalog version.

    Use get_baseline_templates first to find the OS version UUID.
    Supports: page, pagesize. The API does not support server-side name
    filtering — all policies are returned and must be filtered client-side.
    """
    params = {k: v for k, v in kwargs.items() if v is not None}
    return _get(auth, f"/api/mdm/baselines/catalogs/{os_version_uuid}/policies",
                params=params, accept=ACCEPT_V1)


def get_baseline_policy(auth: UEMAuth, policy_uuid: str) -> dict:
    """Get full details of a baseline policy including explanation and status."""
    return _get(auth, f"/api/mdm/baselines/catalogs/policies/{policy_uuid}",
                accept=ACCEPT_V1)


# ---------------------------------------------------------------------------
# App operations
# ---------------------------------------------------------------------------

def search_apps(auth: UEMAuth, **kwargs) -> dict:
    """Search applications. Supports: type (internal/public/purchased),
    applicationname, bundleid, platform, model, status,
    locationgroupid, orderby, page, pagesize."""
    params = {k: v for k, v in kwargs.items() if v is not None}
    return _get(auth, "/api/mam/apps/search", params=params, accept=ACCEPT_V1)


def get_app(auth: UEMAuth, app_id: str, app_type: str = "internal") -> dict:
    """Get full details of an application by its numeric ID.

    app_type: internal, public, or purchased.
    Enriches the response with ApplicationFileName from the search endpoint
    (the detail endpoint omits it).
    """
    detail = _get(auth, f"/api/mam/apps/{app_type}/{app_id}", accept=ACCEPT_V1)
    if not detail.get("ApplicationFileName"):
        search = _get(auth, "/api/mam/apps/search",
                      params={"applicationname": detail.get("ApplicationName", ""),
                              "pagesize": 500},
                      accept=ACCEPT_V1)
        for app in search.get("Application", []):
            if str(app.get("Id", {}).get("Value")) == str(app_id):
                detail["ApplicationFileName"] = app.get("ApplicationFileName")
                break
    return detail


def download_app_blob(auth: UEMAuth, blob_uuid: str, output_dir: str,
                      filename: str = "") -> dict:
    """Download an app binary blob to disk.

    Returns the file path and size. Use get_app first to find the
    ApplicationFileBlobGUID.
    """
    import os
    url = f"{auth.api_base_url}/api/mam/blobs/downloadblob/{blob_uuid}"
    headers = {
        "Authorization": f"Bearer {auth.get_token()}",
        "Accept": "application/json;version=2",
    }
    with httpx.stream("GET", url, headers=headers, timeout=120.0) as resp:
        resp.raise_for_status()
        # Determine filename — caller should provide one from get_app
        if not filename:
            filename = f"{blob_uuid}.bin"
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, filename)
        size = 0
        with open(path, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=8192):
                f.write(chunk)
                size += len(chunk)
    return {"path": path, "size_bytes": size, "blob_uuid": blob_uuid}


# ---------------------------------------------------------------------------
# Script operations
# ---------------------------------------------------------------------------

def search_scripts(auth: UEMAuth, og_uuid: str) -> dict:
    """List all scripts for an organization group."""
    return _get(auth, f"/api/mdm/groups/{og_uuid}/scripts", accept=ACCEPT_V1)


def get_script(auth: UEMAuth, script_uuid: str) -> dict:
    """Get a script by UUID including base64-encoded script_data."""
    return _get(auth, f"/api/mdm/scripts/{script_uuid}", accept=ACCEPT_V1)


def search_sensors(auth: UEMAuth, og_uuid: str) -> dict:
    """List all sensors for an organization group."""
    return _get(auth, f"/api/mdm/devicesensors/list/{og_uuid}", accept=ACCEPT_V2)


def get_sensor(auth: UEMAuth, sensor_uuid: str) -> dict:
    """Get a sensor by UUID including base64-encoded script_data."""
    return _get(auth, f"/api/mdm/devicesensors/{sensor_uuid}", accept=ACCEPT_V2)


def create_script(
    auth: UEMAuth,
    og_uuid: str,
    name: str,
    platform: str,
    script_type: str,
    script_content: str,
    description: str = "",
    execution_context: str = "SYSTEM",
    timeout: int = 120,
) -> dict:
    """Create a script for an organization group (base64-encodes script_content)."""
    body = {
        "name": name,
        "description": description,
        "platform": _normalize_platform(platform),
        "script_type": script_type.upper(),
        "execution_context": execution_context.upper(),
        "timeout": timeout,
        "script_data": base64.b64encode(script_content.encode()).decode(),
        "allowed_in_catalog": False,
    }
    return _post(auth, f"/api/mdm/groups/{og_uuid}/scripts", body=body, accept=ACCEPT_V1)


_SCRIPT_READONLY_KEYS = {"script_uuid", "version", "assignment_count",
                         "created_or_modified_by", "created_or_modified_on"}


def create_script_from_json(auth: UEMAuth, script_json: str) -> dict:
    """Create a script from a JSON body (same schema returned by get_script).

    Strips read-only fields and posts to the create endpoint.
    The organization_group_uuid in the body determines the target OG.
    """
    import json as _json
    body = _json.loads(script_json) if isinstance(script_json, str) else script_json
    og_uuid = body.get("organization_group_uuid")
    if not og_uuid:
        raise ValueError("organization_group_uuid is required in the script JSON")
    cleaned = {k: v for k, v in body.items() if k not in _SCRIPT_READONLY_KEYS}
    return _post(auth, f"/api/mdm/groups/{og_uuid}/scripts", body=cleaned, accept=ACCEPT_V1)


# ---------------------------------------------------------------------------
# Sensor operations
# ---------------------------------------------------------------------------

def create_sensor(
    auth: UEMAuth,
    og_uuid: str,
    name: str,
    platform: str,
    query_type: str,
    script_content: str,
    description: str = "",
    response_type: str = "STRING",
    execution_context: str = "SYSTEM",
) -> dict:
    """Create a sensor for an organization group (base64-encodes script_content).

    Uses the V2 sensor endpoint which supports POWERSHELL, PYTHON, BASH, and ZSH.
    """
    body = {
        "name": name,
        "description": description,
        "organization_group_uuid": og_uuid,
        "platform": _normalize_platform(platform),
        "query_type": query_type.upper(),
        "query_response_type": response_type.upper(),
        "execution_context": execution_context.upper(),
        "script_data": base64.b64encode(script_content.encode()).decode(),
    }
    return _post(auth, "/api/mdm/devicesensors", body=body, accept=ACCEPT_V2)


_SENSOR_READONLY_KEYS = {"uuid", "is_read_only", "last_modified_by",
                         "last_modified_on", "assignment_count"}


def create_sensor_from_json(auth: UEMAuth, sensor_json: str) -> dict:
    """Create a sensor from a JSON body (same schema returned by get_sensor).

    Strips read-only fields and posts to the create endpoint.
    The organization_group_uuid in the body determines the target OG.
    """
    import json as _json
    body = _json.loads(sensor_json) if isinstance(sensor_json, str) else sensor_json
    if not body.get("organization_group_uuid"):
        raise ValueError("organization_group_uuid is required in the sensor JSON")
    cleaned = {k: v for k, v in body.items() if k not in _SENSOR_READONLY_KEYS}
    return _post(auth, "/api/mdm/devicesensors", body=cleaned, accept=ACCEPT_V2)
