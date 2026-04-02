"""Cross-environment migration functions for Workspace ONE UEM resources.

Each function reads resources from a source environment/OG and creates
them in a destination environment/OG, returning a summary of results.
"""
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

import httpx

from wingman_mcp.auth import UEMAuth
from wingman_mcp import uem_api


# ---------------------------------------------------------------------------
# Scripts
# ---------------------------------------------------------------------------

def migrate_scripts(
    source_auth: UEMAuth,
    dest_auth: UEMAuth,
    source_og_uuid: str,
    dest_og_uuid: str,
) -> dict:
    """Migrate all scripts from source OG to destination OG."""
    migrated = []
    skipped = []
    errors = []

    # Get all scripts from source
    source_data = uem_api.search_scripts(source_auth, source_og_uuid)
    source_scripts = source_data if isinstance(source_data, list) else source_data.get("SearchResults", source_data.get("scripts", []))
    if not source_scripts:
        return {"migrated": [], "skipped": [], "errors": [], "summary": "No scripts found in source."}

    # Get existing script names in destination to avoid duplicates
    try:
        dest_data = uem_api.search_scripts(dest_auth, dest_og_uuid)
        dest_scripts = dest_data if isinstance(dest_data, list) else dest_data.get("SearchResults", dest_data.get("scripts", []))
    except Exception:
        dest_scripts = []
    dest_names = {s.get("name", "").lower() for s in dest_scripts}

    for script_summary in source_scripts:
        script_uuid = script_summary.get("script_uuid")
        script_name = script_summary.get("name", "unknown")

        if script_name.lower() in dest_names:
            skipped.append({"name": script_name, "reason": "already exists in destination"})
            continue

        try:
            # Fetch full script details
            full_script = uem_api.get_script(source_auth, script_uuid)

            # Update OG UUID for destination
            full_script["organization_group_uuid"] = dest_og_uuid

            # Strip read-only fields
            for key in uem_api._SCRIPT_READONLY_KEYS:
                full_script.pop(key, None)

            # Create in destination
            result = uem_api.create_script_from_json(dest_auth, full_script)
            migrated.append({"name": script_name, "result": "created"})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                skipped.append({"name": script_name, "reason": "conflict (already exists)"})
            else:
                errors.append({"name": script_name, "error": str(e)})
        except Exception as e:
            errors.append({"name": script_name, "error": str(e)})

    return {
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
        "summary": f"Migrated {len(migrated)}, skipped {len(skipped)}, errors {len(errors)} of {len(source_scripts)} scripts.",
    }


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------

def migrate_sensors(
    source_auth: UEMAuth,
    dest_auth: UEMAuth,
    source_og_uuid: str,
    dest_og_uuid: str,
) -> dict:
    """Migrate all sensors from source OG to destination OG."""
    migrated = []
    skipped = []
    errors = []

    # Get all sensors from source
    source_data = uem_api.search_sensors(source_auth, source_og_uuid)
    source_sensors = source_data if isinstance(source_data, list) else source_data.get("SearchResults", source_data.get("sensors", []))
    if not source_sensors:
        return {"migrated": [], "skipped": [], "errors": [], "summary": "No sensors found in source."}

    # Get existing sensor names in destination
    try:
        dest_data = uem_api.search_sensors(dest_auth, dest_og_uuid)
        dest_sensors = dest_data if isinstance(dest_data, list) else dest_data.get("SearchResults", dest_data.get("sensors", []))
    except Exception:
        dest_sensors = []
    dest_names = {s.get("name", "").lower() for s in dest_sensors}

    for sensor_summary in source_sensors:
        sensor_uuid = sensor_summary.get("uuid")
        sensor_name = sensor_summary.get("name", "unknown")

        if sensor_name.lower() in dest_names:
            skipped.append({"name": sensor_name, "reason": "already exists in destination"})
            continue

        try:
            # Fetch full sensor details
            full_sensor = uem_api.get_sensor(source_auth, sensor_uuid)

            # Update OG UUID for destination
            full_sensor["organization_group_uuid"] = dest_og_uuid

            # Strip read-only fields
            for key in uem_api._SENSOR_READONLY_KEYS:
                full_sensor.pop(key, None)

            # Create in destination
            result = uem_api.create_sensor_from_json(dest_auth, full_sensor)
            migrated.append({"name": sensor_name, "result": "created"})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                skipped.append({"name": sensor_name, "reason": "conflict (already exists)"})
            else:
                errors.append({"name": sensor_name, "error": str(e)})
        except Exception as e:
            errors.append({"name": sensor_name, "error": str(e)})

    return {
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
        "summary": f"Migrated {len(migrated)}, skipped {len(skipped)}, errors {len(errors)} of {len(source_sensors)} sensors.",
    }


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

# Profile General fields that are environment-specific and must be stripped
_PROFILE_STRIP_KEYS = {"ProfileId", "ProfileUuid", "Version"}

# Platform mapping from profile data to create_profile platform arg
_PROFILE_PLATFORM_MAP = {
    "Apple": "Apple",
    "AppleOsX": "AppleOsX",
    "Android": "Android",
    "WinRT": "WinRT",
}


def migrate_profiles(
    source_auth: UEMAuth,
    dest_auth: UEMAuth,
    source_og_id: str,
    dest_og_id: str,
    platform: Optional[str] = None,
) -> dict:
    """Migrate V2-compatible profiles from source OG to destination OG."""
    migrated = []
    skipped = []
    errors = []

    # Search profiles in source
    search_params: dict[str, Any] = {"organizationgroupid": int(source_og_id), "pagesize": 500}
    if platform:
        search_params["platform"] = platform

    source_data = uem_api.search_profiles(source_auth, **search_params)
    source_profiles = source_data.get("ProfileList", [])
    if not source_profiles:
        return {"migrated": [], "skipped": [], "errors": [], "summary": "No profiles found in source."}

    for profile_summary in source_profiles:
        profile_id = str(profile_summary.get("ProfileId", ""))
        profile_name = profile_summary.get("ProfileName", "unknown")
        profile_platform = profile_summary.get("Platform", "")

        # Map platform for creation
        create_platform = _PROFILE_PLATFORM_MAP.get(profile_platform)
        if not create_platform:
            skipped.append({"name": profile_name, "reason": f"unsupported platform: {profile_platform}"})
            continue

        try:
            # Fetch full profile (V2)
            full_profile = uem_api.get_profile(source_auth, profile_id)

            # Check if this is a V2 response (has "General" key)
            if "General" not in full_profile:
                skipped.append({"name": profile_name, "reason": "non-V2 profile (read-only, cannot migrate)"})
                continue

            # Update OG ID for destination
            general = full_profile["General"]
            general["ManagedLocationGroupID"] = dest_og_id

            # Strip environment-specific fields
            for key in _PROFILE_STRIP_KEYS:
                general.pop(key, None)

            # Strip smart group assignments (IDs differ between environments)
            if "AssignedSmartGroups" in general:
                general.pop("AssignedSmartGroups")

            # Create in destination
            result = uem_api.create_profile(dest_auth, create_platform, full_profile)
            migrated.append({"name": profile_name, "platform": profile_platform, "result": "created"})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400:
                skipped.append({"name": profile_name, "reason": "non-V2 payload (cannot migrate)"})
            elif e.response.status_code == 409:
                skipped.append({"name": profile_name, "reason": "conflict (already exists)"})
            else:
                errors.append({"name": profile_name, "error": str(e)})
        except Exception as e:
            errors.append({"name": profile_name, "error": str(e)})

    return {
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
        "summary": f"Migrated {len(migrated)}, skipped {len(skipped)}, errors {len(errors)} of {len(source_profiles)} profiles.",
    }


# ---------------------------------------------------------------------------
# Apps (internal only)
# ---------------------------------------------------------------------------

def migrate_apps(
    source_auth: UEMAuth,
    dest_auth: UEMAuth,
    source_og_id: str,
    dest_og_id: str,
) -> dict:
    """Migrate internal apps from source OG to destination OG.

    Downloads each app binary from source, uploads to destination,
    then creates the app with matching metadata.
    """
    migrated = []
    skipped = []
    errors = []

    # Search internal apps in source
    source_data = uem_api.search_apps(
        source_auth, type="internal",
        locationgroupid=int(source_og_id), pagesize=500,
    )
    source_apps = source_data.get("Application", [])
    if not source_apps:
        return {"migrated": [], "skipped": [], "errors": [], "summary": "No internal apps found in source."}

    # Use temp directory for blob transfers
    temp_dir = os.path.join(Path.home(), ".wingman-mcp", "temp")
    os.makedirs(temp_dir, exist_ok=True)

    for app_summary in source_apps:
        app_id = str(app_summary.get("Id", {}).get("Value", ""))
        app_name = app_summary.get("ApplicationName", "unknown")

        try:
            # Get full app details
            app_detail = uem_api.get_app(source_auth, app_id, app_type="internal")
            blob_uuid = app_detail.get("ApplicationFileBlobGUID") or app_detail.get("BlobId")
            if not blob_uuid:
                skipped.append({"name": app_name, "reason": "no blob UUID found"})
                continue

            filename = app_detail.get("ApplicationFileName", f"{blob_uuid}.bin")

            # Download blob from source
            download_result = uem_api.download_app_blob(
                source_auth, blob_uuid, temp_dir, filename=filename,
            )
            local_path = download_result["path"]

            try:
                # Upload blob to destination
                upload_result = uem_api.upload_app_blob(
                    dest_auth, local_path, int(dest_og_id),
                )
                new_blob_id = upload_result.get("Value") or upload_result.get("value")

                # Build app creation payload
                app_payload = _build_app_payload(app_detail, new_blob_id, int(dest_og_id))

                # Create app in destination
                create_result = uem_api.create_internal_app(dest_auth, app_payload)
                migrated.append({"name": app_name, "result": "created"})
            finally:
                # Clean up temp file
                if os.path.exists(local_path):
                    os.remove(local_path)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                skipped.append({"name": app_name, "reason": "conflict (already exists)"})
            else:
                errors.append({"name": app_name, "error": str(e)})
        except Exception as e:
            errors.append({"name": app_name, "error": str(e)})

    return {
        "migrated": migrated,
        "skipped": skipped,
        "errors": errors,
        "summary": f"Migrated {len(migrated)}, skipped {len(skipped)}, errors {len(errors)} of {len(source_apps)} apps.",
    }


def _build_app_payload(source_detail: dict, new_blob_id: str, dest_og_id: int) -> dict:
    """Build a begininstall payload from source app details."""
    return {
        "ApplicationName": source_detail.get("ApplicationName", ""),
        "BlobId": new_blob_id,
        "DeviceType": source_detail.get("DeviceType", source_detail.get("Platform", "")),
        "PushMode": source_detail.get("PushMode", "Auto"),
        "SupportedModels": source_detail.get("SupportedModels", {}),
        "Description": source_detail.get("Description", ""),
        "EnableProvisioning": source_detail.get("EnableProvisioning", False),
        "UploadViaLink": False,
        "LocationGroupId": dest_og_id,
        "FileName": source_detail.get("ApplicationFileName", ""),
        "SupportedProcessorArchitecture": source_detail.get("SupportedProcessorArchitecture", ""),
        "ActualFileVersion": source_detail.get("ActualFileVersion", source_detail.get("AppVersion", "")),
    }
