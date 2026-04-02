"""Export UEM resources to disk as a backup.

Reads scripts, sensors, profiles, and apps from a UEM environment
and saves them as JSON files (plus app binaries) in a timestamped
export directory.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from wingman_mcp.auth import UEMAuth
from wingman_mcp import uem_api

ALL_RESOURCE_TYPES = ["scripts", "sensors", "profiles", "apps"]


def _sanitize_filename(name: str) -> str:
    """Replace non-filesystem-safe characters with underscores."""
    sanitized = re.sub(r'[^\w.\-]', '_', name)
    return sanitized[:80]


def _write_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Scripts
# ---------------------------------------------------------------------------

def _export_scripts(auth: UEMAuth, og_uuid: str, export_dir: str) -> dict:
    """Export all scripts from an OG to disk."""
    out_dir = os.path.join(export_dir, "scripts")
    os.makedirs(out_dir, exist_ok=True)

    exported = []
    errors = []

    source_data = uem_api.search_scripts(auth, og_uuid)
    scripts = (source_data if isinstance(source_data, list)
               else source_data.get("SearchResults", source_data.get("scripts", [])))

    for script_summary in scripts:
        script_uuid = script_summary.get("script_uuid")
        script_name = script_summary.get("name", "unknown")

        try:
            full_script = uem_api.get_script(auth, script_uuid)
            filename = f"{_sanitize_filename(script_name)}__{script_uuid}.json"
            _write_json(os.path.join(out_dir, filename), full_script)
            exported.append({"name": script_name, "file": f"scripts/{filename}"})
        except Exception as e:
            errors.append({"name": script_name, "error": str(e)})

    return {"exported": len(exported), "errors": errors, "items": exported}


# ---------------------------------------------------------------------------
# Sensors
# ---------------------------------------------------------------------------

def _export_sensors(auth: UEMAuth, og_uuid: str, export_dir: str) -> dict:
    """Export all sensors from an OG to disk."""
    out_dir = os.path.join(export_dir, "sensors")
    os.makedirs(out_dir, exist_ok=True)

    exported = []
    errors = []

    source_data = uem_api.search_sensors(auth, og_uuid)
    sensors = (source_data if isinstance(source_data, list)
               else source_data.get("SearchResults", source_data.get("sensors", [])))

    for sensor_summary in sensors:
        sensor_uuid = sensor_summary.get("uuid")
        sensor_name = sensor_summary.get("name", "unknown")

        try:
            full_sensor = uem_api.get_sensor(auth, sensor_uuid)
            filename = f"{_sanitize_filename(sensor_name)}__{sensor_uuid}.json"
            _write_json(os.path.join(out_dir, filename), full_sensor)
            exported.append({"name": sensor_name, "file": f"sensors/{filename}"})
        except Exception as e:
            errors.append({"name": sensor_name, "error": str(e)})

    return {"exported": len(exported), "errors": errors, "items": exported}


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def _export_profiles(auth: UEMAuth, og_id: str, export_dir: str) -> dict:
    """Export all profiles from an OG to disk."""
    out_dir = os.path.join(export_dir, "profiles")
    os.makedirs(out_dir, exist_ok=True)

    exported = []
    errors = []

    source_data = uem_api.search_profiles(
        auth, organizationgroupid=int(og_id), pagesize=500,
    )
    profiles = source_data.get("ProfileList", [])

    for profile_summary in profiles:
        profile_id = str(profile_summary.get("ProfileId", ""))
        profile_name = profile_summary.get("ProfileName", "unknown")

        try:
            full_profile = uem_api.get_profile(auth, profile_id)
            # Tag with export format so a future import knows what it's dealing with
            is_v2 = "General" in full_profile
            wrapper = {
                "_export_meta": {
                    "format": "v2" if is_v2 else "metadata_transforms",
                    "profile_id": profile_id,
                    "profile_name": profile_name,
                    "platform": profile_summary.get("Platform", ""),
                },
                "data": full_profile,
            }
            filename = f"{_sanitize_filename(profile_name)}__{profile_id}.json"
            _write_json(os.path.join(out_dir, filename), wrapper)
            exported.append({
                "name": profile_name,
                "file": f"profiles/{filename}",
                "format": "v2" if is_v2 else "metadata_transforms",
            })
        except Exception as e:
            errors.append({"name": profile_name, "error": str(e)})

    return {"exported": len(exported), "errors": errors, "items": exported}


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------

def _export_apps(
    auth: UEMAuth, og_id: str, export_dir: str, include_blobs: bool = True,
) -> dict:
    """Export all internal apps from an OG to disk."""
    meta_dir = os.path.join(export_dir, "apps")
    blob_dir = os.path.join(export_dir, "apps", "blobs")
    os.makedirs(meta_dir, exist_ok=True)
    if include_blobs:
        os.makedirs(blob_dir, exist_ok=True)

    exported = []
    errors = []

    source_data = uem_api.search_apps(
        auth, locationgroupid=int(og_id), pagesize=500,
    )
    all_apps = source_data.get("Application", [])
    # Only internal apps have downloadable blobs
    apps = [a for a in all_apps if a.get("AppType", "").lower() == "internal"]

    for app_summary in apps:
        app_id = str(app_summary.get("Id", {}).get("Value", ""))
        app_name = app_summary.get("ApplicationName", "unknown")

        try:
            app_detail = uem_api.get_app(auth, app_id, app_type="internal")

            blob_file = None
            if include_blobs:
                blob_uuid = (app_detail.get("ApplicationFileBlobGUID")
                             or app_detail.get("BlobId"))
                if blob_uuid:
                    blob_filename = app_detail.get("ApplicationFileName", f"{blob_uuid}.bin")
                    result = uem_api.download_app_blob(
                        auth, blob_uuid, blob_dir, filename=blob_filename,
                    )
                    blob_file = f"apps/blobs/{blob_filename}"

            wrapper = {
                "_export_meta": {
                    "app_id": app_id,
                    "app_name": app_name,
                    "blob_file": blob_file,
                },
                "data": app_detail,
            }
            filename = f"{_sanitize_filename(app_name)}__{app_id}.json"
            _write_json(os.path.join(meta_dir, filename), wrapper)
            exported.append({"name": app_name, "file": f"apps/{filename}", "blob": blob_file})
        except Exception as e:
            errors.append({"name": app_name, "error": str(e)})

    return {"exported": len(exported), "errors": errors, "items": exported}


# ---------------------------------------------------------------------------
# Main export orchestrator
# ---------------------------------------------------------------------------

def export_all(
    auth: UEMAuth,
    group_id: Optional[str] = None,
    output_dir: Optional[str] = None,
    resource_types: Optional[list[str]] = None,
    include_app_blobs: bool = True,
) -> dict:
    """Export all UEM resources from an OG to a timestamped directory on disk.

    If group_id is provided, looks up that OG by its string group ID code.
    If omitted, auto-detects the top-level OG for the authenticated account.
    If output_dir is not provided, defaults to ~/.wingman-mcp/exports.

    Returns a summary dict with counts, file paths, and any errors.
    """
    # Resolve OG — by group_id if provided, otherwise top-level
    og = uem_api.resolve_og(auth, group_id=group_id)
    og_uuid = og["og_uuid"]
    og_id = og["og_id"]

    # Default output directory
    if not output_dir:
        output_dir = os.path.join(str(Path.home()), ".wingman-mcp", "exports")

    types = resource_types or ALL_RESOURCE_TYPES

    # Create timestamped export directory
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    export_dir = os.path.join(output_dir, f"export_{timestamp}")
    os.makedirs(export_dir, exist_ok=True)

    results: dict[str, Any] = {}
    all_errors: list[dict] = []

    if "scripts" in types:
        results["scripts"] = _export_scripts(auth, og_uuid, export_dir)
        all_errors.extend(results["scripts"]["errors"])

    if "sensors" in types:
        results["sensors"] = _export_sensors(auth, og_uuid, export_dir)
        all_errors.extend(results["sensors"]["errors"])

    if "profiles" in types:
        results["profiles"] = _export_profiles(auth, og_id, export_dir)
        all_errors.extend(results["profiles"]["errors"])

    if "apps" in types:
        results["apps"] = _export_apps(auth, og_id, export_dir, include_blobs=include_app_blobs)
        all_errors.extend(results["apps"]["errors"])

    # Write manifest
    counts = {t: results[t]["exported"] for t in results}
    manifest = {
        "wingman_mcp_version": "0.4.0",
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
        "api_base_url": auth.api_base_url,
        "organization_group": {
            "og_uuid": og_uuid,
            "og_id": og_id,
            "name": og["name"],
            "group_id": og["group_id"],
        },
        "resource_types_exported": list(results.keys()),
        "counts": counts,
        "errors": all_errors,
    }
    _write_json(os.path.join(export_dir, "manifest.json"), manifest)

    total = sum(counts.values())
    return {
        "export_dir": export_dir,
        "organization_group": og["name"],
        "counts": counts,
        "total_exported": total,
        "total_errors": len(all_errors),
        "errors": all_errors,
        "summary": f"Exported {total} resources to {export_dir} ({len(all_errors)} errors).",
    }
