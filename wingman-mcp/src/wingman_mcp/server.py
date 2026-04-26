"""MCP server exposing Workspace ONE UEM documentation search tools."""
import hashlib
import json
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from wingman_mcp.config import get_store_dir, stores_exist, STORE_KEYS
from wingman_mcp.search import (
    search_uem, search_api, search_release_notes, search_product_docs,
)

app = Server("wingman-mcp")

# Lazy-loaded stores and auth
_stores: dict[str, Any] = {}
_embeddings = None
# UEM auth cache.
# In local/stdio mode: keyed by environment name.
# In HTTP mode: keyed by SHA-256 of credential values (so different users get
# separate UEMAuth instances with their own token caches).
_auths: dict[str, Any] = {}

# Non-UEM product API client cache, keyed by (product, env_name).
_product_clients: dict[tuple[str, str], Any] = {}


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        from wingman_mcp.embeddings import LocalEmbeddings
        _embeddings = LocalEmbeddings()
    return _embeddings


def _get_auth(env_name: str = "default"):
    """Return a UEMAuth instance or None.

    In HTTP server mode, credentials come from the per-request ContextVar set
    by CredentialHeaderMiddleware.  In local stdio mode, credentials are loaded
    from the OS keychain / config file as usual.
    """
    from wingman_mcp.request_context import _is_http_request, _request_credentials

    if _is_http_request.get():
        creds = _request_credentials.get()
        if creds is None:
            return None
        # Cache UEMAuth by a fingerprint of the credentials so that repeated
        # calls within the same process reuse the token cache.
        fingerprint = hashlib.sha256(
            f"{creds['client_id']}:{creds['client_secret']}:{creds['token_url']}:{creds['api_base_url']}".encode()
        ).hexdigest()
        if fingerprint not in _auths:
            from wingman_mcp.auth import UEMAuth
            _auths[fingerprint] = UEMAuth(creds)
        return _auths[fingerprint]

    # Local/stdio mode: load from OS keychain + config file.
    if env_name not in _auths:
        from wingman_mcp.credentials import load_credentials
        creds = load_credentials(env_name)
        if creds is None:
            return None
        from wingman_mcp.auth import UEMAuth
        _auths[env_name] = UEMAuth(creds)
    return _auths[env_name]


def _get_store(store_key: str):
    if store_key not in _stores:
        from langchain_chroma import Chroma
        _stores[store_key] = Chroma(
            persist_directory=get_store_dir(store_key),
            embedding_function=_get_embeddings(),
        )
    return _stores[store_key]


TOOLS = [
    Tool(
        name="search_uem_docs",
        description=(
            "Search Omnissa Workspace ONE UEM product documentation. "
            "Covers configuration guides, admin consoles, enrollment, profiles, "
            "smart groups, compliance, conditional access, SAML/SSO, and more. "
            "Returns relevant documentation chunks with source URLs."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query about Workspace ONE UEM",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="search_api_reference",
        description=(
            "Search Omnissa REST API endpoint documentation. "
            "Supports product filter (default: 'uem'). Valid products: "
            "uem, horizon, horizon_cloud, app_volumes, uag, access, "
            "intelligence, identity_service. (DEM and ThinApp have no API.) "
            "For UEM covers MDM/MAM/MCM/MEM/System groups; for others "
            "returns method, path, summary, parameters from the product's "
            "OpenAPI spec on developer.omnissa.com."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query about REST APIs (e.g. 'enroll device', 'GET profiles')",
                },
                "product": {
                    "type": "string",
                    "description": (
                        "Product slug. Default: 'uem'. One of: uem, horizon, "
                        "horizon_cloud, app_volumes, uag, access, intelligence, "
                        "identity_service."
                    ),
                    "default": "uem",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="search_omnissa_docs",
        description=(
            "Search Omnissa product documentation for a specific product. "
            "Covers Horizon, Horizon Cloud, App Volumes, Unified Access "
            "Gateway, ThinApp, Dynamic Environment Manager, Workspace ONE "
            "UEM, Workspace ONE Access, Intelligence, Omnissa Identity "
            "Service, the WS1 sub-products (MTD, ServiceNow, Hub Services, "
            "XR Hub, PIV-D Manager, Admin Assistant, ENS, SEG, Okta SCIM, "
            "AirWatch Cloud Connector), and Omnissa TechZone.\n\n"
            "When to pick which product:\n"
            "  - product='techzone' for 'how do I X?', 'what's the best way "
            "    to Y?', design / reference architecture / tutorial / "
            "    deployment-pattern questions that span products. TechZone "
            "    is curated reference content, not config reference.\n"
            "  - product='<specific>' for product-specific configuration, "
            "    admin console settings, payload reference, troubleshooting.\n"
            "  - For a Workspace ONE UEM question, prefer 'search_uem_docs' "
            "    which has tuned multi-family scoring; this tool is the "
            "    fallback for everything else.\n\n"
            "Run 'wingman-mcp ingest --list' on the host to see which "
            "product stores have been built — only built stores can be "
            "searched."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "product": {
                    "type": "string",
                    "description": (
                        "Product slug. One of: uem, horizon, horizon_cloud, "
                        "app_volumes, uag, thinapp, dem, access, intelligence, "
                        "identity_service, mtd, servicenow, hub_services, "
                        "xr_hub, pivd_manager, admin_assistant, ens, seg, "
                        "okta_scim, aw_cloud_connector, techzone."
                    ),
                },
                "query": {
                    "type": "string",
                    "description": "Natural language search query for the chosen product",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 10)",
                    "default": 10,
                },
            },
            "required": ["product", "query"],
        },
    ),
    Tool(
        name="search_release_notes",
        description=(
            "Search Omnissa product release notes for feature changes, "
            "bug fixes, resolved issues, and new capabilities. "
            "Supports product filter (default: 'uem'). Valid products: "
            "uem, horizon, horizon_cloud, app_volumes, uag, dem, thinapp, "
            "access, intelligence, identity_service. "
            "Supports version filter where applicable (e.g. UEM '2602', "
            "Horizon '2603', Access '24.12'). Version input is normalized: "
            "'2412' and '24.12' match the same Access bundle."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query about release notes or version changes",
                },
                "product": {
                    "type": "string",
                    "description": (
                        "Product slug. Default: 'uem'. One of: uem, horizon, "
                        "horizon_cloud, app_volumes, uag, dem, thinapp, access, "
                        "intelligence, identity_service."
                    ),
                    "default": "uem",
                },
                "version": {
                    "type": "string",
                    "description": (
                        "Optional version filter. Examples: UEM '2602', Horizon "
                        "'2603', Access '24.12' (or '2412' — both match)."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 15)",
                    "default": 15,
                },
            },
            "required": ["query"],
        },
    ),
    # -----------------------------------------------------------------------
    # UEM API tools (require auth via 'wingman-mcp auth set')
    # -----------------------------------------------------------------------
    Tool(
        name="uem_list_environments",
        description=(
            "List all configured UEM environments. "
            "Environments are set up with 'wingman-mcp auth set --env <name>'. "
            "Use environment names in the 'env' parameter of other UEM tools."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="uem_search_devices",
        description=(
            "Search for managed devices in the user's Workspace ONE UEM environment. "
            "Requires UEM API auth to be configured ('wingman-mcp auth set'). "
            "Filters: user (username), model, platform (Apple/Android/WinRT), "
            "ownership (CorporateOwned/EmployeeOwned/Shared), compliantstatus (Compliant/NonCompliant), "
            "seensince (yyyy-MM-dd), lgid (organization group ID). "
            "Returns device list with details like serial, platform, OS, compliance, enrollment status."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user": {"type": "string", "description": "Filter by enrollment username"},
                "model": {"type": "string", "description": "Filter by device model"},
                "platform": {"type": "string", "description": "Filter by platform (Apple, Android, WinRT)"},
                "ownership": {"type": "string", "description": "Filter by ownership (CorporateOwned, EmployeeOwned, Shared)"},
                "compliantstatus": {"type": "string", "description": "Filter by compliance (Compliant, NonCompliant)"},
                "seensince": {"type": "string", "description": "Filter devices seen since date (yyyy-MM-dd)"},
                "lgid": {"type": "integer", "description": "Filter by organization group ID"},
                "page": {"type": "integer", "description": "Page number (default: 0)"},
                "pagesize": {"type": "integer", "description": "Results per page (default: 50, max: 500)"},
            },
            "required": [],
        },
    ),
    Tool(
        name="uem_get_device",
        description=(
            "Get detailed information for a specific managed device by its numeric ID. "
            "Returns full device details: serial number, UDID, platform, OS version, "
            "compliance status, enrollment status, last seen, installed profiles and apps counts, etc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "The numeric device ID"},
            },
            "required": ["device_id"],
        },
    ),
    Tool(
        name="uem_get_device_profiles",
        description=(
            "Get the list of profiles installed on a specific device. "
            "Returns profile names, versions, install status, and payload types."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "The numeric device ID"},
                "page": {"type": "integer", "description": "Page number (default: 0)"},
                "pagesize": {"type": "integer", "description": "Results per page (default: 50)"},
            },
            "required": ["device_id"],
        },
    ),
    Tool(
        name="uem_get_device_apps",
        description=(
            "Get the list of apps installed on a specific device. "
            "Returns app names, versions, bundle IDs, install status, and managed status."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "The numeric device ID"},
                "page": {"type": "integer", "description": "Page number (default: 0)"},
                "pagesize": {"type": "integer", "description": "Results per page (default: 50)"},
            },
            "required": ["device_id"],
        },
    ),
    Tool(
        name="uem_get_device_security",
        description=(
            "Get security information for a specific device. "
            "Returns encryption status, passcode compliance, compromised status, "
            "data protection, firewall status, and other security attributes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "The numeric device ID"},
            },
            "required": ["device_id"],
        },
    ),
    Tool(
        name="uem_get_device_network",
        description=(
            "Get network information for a specific device. "
            "Returns IP addresses, MAC addresses, WiFi SSID, cellular info, roaming status."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "The numeric device ID"},
            },
            "required": ["device_id"],
        },
    ),
    Tool(
        name="uem_send_device_command",
        description=(
            "Send a management command to a specific device. "
            "Common commands: DeviceQuery (refresh device info), Lock, "
            "EnterpriseWipe (remove managed data), SyncDevice, ClearPasscode. "
            "Use with caution — commands like EnterpriseWipe are destructive."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "The numeric device ID"},
                "command": {"type": "string", "description": "Command to send (e.g. DeviceQuery, Lock, EnterpriseWipe, SyncDevice, ClearPasscode)"},
            },
            "required": ["device_id", "command"],
        },
    ),
    Tool(
        name="uem_search_users",
        description=(
            "Search for enrollment users in the UEM environment. "
            "Filters: firstname, lastname, email, username, locationgroupid, role. "
            "Returns user details including enrollment status and assigned devices."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "firstname": {"type": "string", "description": "Filter by first name"},
                "lastname": {"type": "string", "description": "Filter by last name"},
                "email": {"type": "string", "description": "Filter by email"},
                "username": {"type": "string", "description": "Filter by username"},
                "locationgroupid": {"type": "integer", "description": "Filter by organization group ID"},
                "role": {"type": "string", "description": "Filter by role"},
                "page": {"type": "integer", "description": "Page number (default: 0)"},
                "pagesize": {"type": "integer", "description": "Results per page (default: 50)"},
            },
            "required": [],
        },
    ),
    Tool(
        name="uem_get_user",
        description=(
            "Get detailed information for a specific enrollment user by numeric user ID."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "The numeric user ID"},
            },
            "required": ["user_id"],
        },
    ),
    Tool(
        name="uem_search_organization_groups",
        description=(
            "Search for organization groups (OGs) in the UEM hierarchy. "
            "Filters: name, groupid. "
            "Returns OG details including type (Customer/Container/etc), "
            "group ID, parent, and country."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Filter by OG name"},
                "groupid": {"type": "string", "description": "Filter by group ID code"},
                "page": {"type": "integer", "description": "Page number (default: 0)"},
                "pagesize": {"type": "integer", "description": "Results per page (default: 50)"},
            },
            "required": [],
        },
    ),
    Tool(
        name="uem_get_organization_group",
        description=(
            "Get details of a specific organization group by its numeric OG ID. "
            "Returns name, group ID, type, country, locale, and timezone."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "og_id": {"type": "string", "description": "The numeric organization group ID"},
            },
            "required": ["og_id"],
        },
    ),
    Tool(
        name="uem_get_og_children",
        description=(
            "Get the child organization groups under a given OG. "
            "Useful for exploring the OG hierarchy."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "og_id": {"type": "string", "description": "The numeric organization group ID"},
            },
            "required": ["og_id"],
        },
    ),
    Tool(
        name="uem_search_smart_groups",
        description=(
            "Search for smart groups. "
            "Filters: name, organizationgroupid. "
            "Returns smart group details including criteria, device count, and assignments."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Filter by smart group name"},
                "organizationgroupid": {"type": "integer", "description": "Filter by organization group ID"},
                "page": {"type": "integer", "description": "Page number (default: 0)"},
                "pagesize": {"type": "integer", "description": "Results per page (default: 50)"},
            },
            "required": [],
        },
    ),
    Tool(
        name="uem_search_profiles",
        description=(
            "Search for device profiles configured in UEM. "
            "Filters: searchtext, type, platform (Apple/Android/WinRT), status, organizationgroupid. "
            "Returns profile names, platforms, assignment status, and payload types."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "searchtext": {"type": "string", "description": "Search text to match profile names"},
                "type": {"type": "string", "description": "Profile type filter"},
                "platform": {"type": "string", "description": "Platform filter (Apple, Android, WinRT)"},
                "status": {"type": "string", "description": "Status filter (Active, Inactive)"},
                "organizationgroupid": {"type": "integer", "description": "Filter by organization group ID"},
                "page": {"type": "integer", "description": "Page number (default: 0)"},
                "pagesize": {"type": "integer", "description": "Results per page (default: 50)"},
            },
            "required": [],
        },
    ),
    Tool(
        name="uem_get_profile",
        description=(
            "Get full details of a specific device profile by its numeric profile ID. "
            "For Windows and profiles with V2-supported payloads (Custom Settings, WiFi, "
            "VPN, SSO Extension, etc.), returns a General + payload structure that can be "
            "round-tripped with uem_create_profile. For profiles with non-V2 payloads "
            "(Dock, Disk Encryption, etc.), returns full payload field values and metadata "
            "via the metadata-transforms endpoint (read-only, cannot be re-uploaded). "
            "Use uem_search_profiles first to find profile IDs."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "profile_id": {"type": "string", "description": "The numeric profile ID"},
            },
            "required": ["profile_id"],
        },
    ),
    Tool(
        name="uem_search_compliance_policies",
        description=(
            "Search for compliance policies in UEM. "
            "Returns policy names, platforms, rules, and actions. "
            "Supports: organizationgroupid, page, pagesize."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "organizationgroupid": {"type": "integer", "description": "Filter by organization group ID"},
                "page": {"type": "integer", "description": "Page number (default: 0)"},
                "pagesize": {"type": "integer", "description": "Results per page (default: 50)"},
            },
            "required": [],
        },
    ),
    Tool(
        name="uem_get_baseline_templates",
        description=(
            "List available security baseline vendor templates (Microsoft, CIS) "
            "with their OS version catalogs. Use the OS version UUID from results "
            "with uem_search_baseline_policies to browse the policy catalog."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="uem_search_baseline_policies",
        description=(
            "List GPO policies in a security baseline catalog version. "
            "Returns policy names, paths, and configuration class. "
            "Use uem_get_baseline_templates first to find the OS version UUID. "
            "The API does not support server-side name filtering. "
            "Supports: page, pagesize."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "os_version_uuid": {"type": "string", "description": "OS version UUID from uem_get_baseline_templates"},
                "page": {"type": "integer", "description": "Page number (default: 0)"},
                "pagesize": {"type": "integer", "description": "Results per page (default: 50)"},
            },
            "required": ["os_version_uuid"],
        },
    ),
    Tool(
        name="uem_get_baseline_policy",
        description=(
            "Get full details of a security baseline policy by its UUID. "
            "Returns the policy name, path, class, full explanation of what "
            "the policy does, and current configuration status. "
            "Use uem_search_baseline_policies first to find policy UUIDs."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "policy_uuid": {"type": "string", "description": "The policy UUID"},
            },
            "required": ["policy_uuid"],
        },
    ),
    Tool(
        name="uem_search_apps",
        description=(
            "Search for applications in UEM. "
            "Filters: type (internal/public/purchased), applicationname, bundleid, "
            "platform, model, status, locationgroupid. "
            "Returns app details including version, platform, assignment status."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "App type (internal, public, purchased)"},
                "applicationname": {"type": "string", "description": "Filter by app name"},
                "bundleid": {"type": "string", "description": "Filter by bundle ID"},
                "platform": {"type": "string", "description": "Platform filter (Apple, Android, WinRT)"},
                "status": {"type": "string", "description": "Status filter (Active, Inactive)"},
                "locationgroupid": {"type": "integer", "description": "Filter by organization group ID"},
                "page": {"type": "integer", "description": "Page number (default: 0)"},
                "pagesize": {"type": "integer", "description": "Results per page (default: 50)"},
            },
            "required": [],
        },
    ),
    Tool(
        name="uem_get_app",
        description=(
            "Get full details of an application by its numeric ID. "
            "Returns app configuration, version, platform, assignments, "
            "deployment settings, and the ApplicationFileBlobGUID needed "
            "to download the binary with uem_download_app_blob. "
            "Use uem_search_apps first to find app IDs."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "app_id": {"type": "string", "description": "The numeric application ID"},
                "app_type": {"type": "string", "description": "App type: internal, public, or purchased (default: internal)"},
            },
            "required": ["app_id"],
        },
    ),
    Tool(
        name="uem_download_app_blob",
        description=(
            "Download an application binary file from UEM to disk. "
            "Use uem_get_app first to find the ApplicationFileBlobGUID. "
            "Saves the file to the specified output directory and returns "
            "the file path and size. Files can be large (hundreds of MB)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "blob_uuid": {"type": "string", "description": "The ApplicationFileBlobGUID from uem_get_app"},
                "output_dir": {"type": "string", "description": "Directory to save the downloaded file"},
                "filename": {"type": "string", "description": "Optional filename (defaults to blob UUID)"},
            },
            "required": ["blob_uuid", "output_dir"],
        },
    ),
    Tool(
        name="uem_create_profile",
        description=(
            "Create a device profile in Workspace ONE UEM from a V2 JSON body. "
            "Accepts the same General + payload JSON returned by uem_get_profile "
            "when V2 is supported. Use uem_get_profile to download, modify the name "
            "or settings, then upload to create a copy. The API assigns a new profile "
            "ID and UUID automatically. "
            "Supports: WinRT (all payloads), Apple and Android (V2 payloads only — "
            "Custom Settings, WiFi, VPN, SCEP, Credentials, SSO Extension, Email, "
            "WebClips). macOS profiles with non-V2 payloads like Dock or Disk "
            "Encryption cannot be created via this tool."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "Target platform: WinRT, Apple, AppleOsX, or Android"},
                "profile_json": {"type": "string", "description": "Full profile V2 JSON body (General + payload sections, same schema as uem_get_profile V2 output)"},
            },
            "required": ["platform", "profile_json"],
        },
    ),
    Tool(
        name="uem_search_scripts",
        description=(
            "List all scripts for an organization group. "
            "Returns script names, UUIDs, platforms, script types, and assignment counts. "
            "Use the script UUID from results with uem_get_script to get full details."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "og_uuid": {"type": "string", "description": "Organization group UUID"},
            },
            "required": ["og_uuid"],
        },
    ),
    Tool(
        name="uem_get_script",
        description=(
            "Get full details of a script by its UUID, including base64-encoded script_data. "
            "The response can be round-tripped with uem_create_script_from_json to create a copy. "
            "Use uem_search_scripts first to find script UUIDs."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "script_uuid": {"type": "string", "description": "The script UUID"},
            },
            "required": ["script_uuid"],
        },
    ),
    Tool(
        name="uem_search_sensors",
        description=(
            "List all sensors for an organization group. "
            "Returns sensor names, UUIDs, platforms, query types, response types, and assignment counts. "
            "Use the sensor UUID from results with uem_get_sensor to get full details."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "og_uuid": {"type": "string", "description": "Organization group UUID"},
            },
            "required": ["og_uuid"],
        },
    ),
    Tool(
        name="uem_get_sensor",
        description=(
            "Get full details of a sensor by its UUID, including base64-encoded script_data. "
            "The response can be round-tripped with uem_create_sensor_from_json to create a copy. "
            "Use uem_search_sensors first to find sensor UUIDs."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "sensor_uuid": {"type": "string", "description": "The sensor UUID"},
            },
            "required": ["sensor_uuid"],
        },
    ),
    Tool(
        name="uem_create_script",
        description=(
            "Create a script in Workspace ONE UEM for an organization group. "
            "Scripts run on managed devices for detection or remediation. "
            "Provide script content as plain text — it is base64-encoded automatically. "
            "Requires UEM API auth to be configured."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "og_uuid": {"type": "string", "description": "Organization group UUID (e.g. 94e8fd6d-cb42-4692-bde0-3cbb9249ee6a)"},
                "name": {"type": "string", "description": "Script name"},
                "description": {"type": "string", "description": "Script description"},
                "platform": {"type": "string", "description": "Target platform: macOS, Windows, or Linux (mapped to API values APPLE_OSX, WIN_RT, LINUX)"},
                "script_type": {"type": "string", "description": "Script language: BASH, POWERSHELL, PYTHON, ZSH"},
                "script_content": {"type": "string", "description": "Script source code as plain text"},
                "execution_context": {"type": "string", "description": "Run as SYSTEM or USER (default: SYSTEM)"},
                "timeout": {"type": "integer", "description": "Execution timeout in seconds (default: 120)"},
            },
            "required": ["og_uuid", "name", "platform", "script_type", "script_content"],
        },
    ),
    Tool(
        name="uem_create_script_from_json",
        description=(
            "Create a script from a JSON body (same schema returned by uem_get_script). "
            "Use this to duplicate or migrate scripts: download with uem_get_script, "
            "modify the name or settings, then upload with this tool. "
            "The script_data should remain base64-encoded as returned by uem_get_script. "
            "Read-only fields (script_uuid, version, assignment_count) are stripped automatically. "
            "Script names only allow letters, numbers, periods, underscores, and spaces."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "script_json": {"type": "string", "description": "Full script JSON body (same schema as uem_get_script output)"},
            },
            "required": ["script_json"],
        },
    ),
    Tool(
        name="uem_create_sensor",
        description=(
            "Create a sensor in Workspace ONE UEM for an organization group. "
            "Sensors run scripts on devices and return a typed value (string, integer, boolean). "
            "Provide script content as plain text — it is base64-encoded automatically. "
            "Requires UEM API auth to be configured."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "og_uuid": {"type": "string", "description": "Organization group UUID"},
                "name": {"type": "string", "description": "Sensor name"},
                "description": {"type": "string", "description": "Sensor description"},
                "platform": {"type": "string", "description": "Target platform: macOS, Windows, or Linux (mapped to API values APPLE_OSX, WIN_RT, LINUX)"},
                "query_type": {"type": "string", "description": "Script language: BASH, POWERSHELL, PYTHON, ZSH"},
                "script_content": {"type": "string", "description": "Sensor script source code as plain text"},
                "response_type": {"type": "string", "description": "Return value type: STRING, INTEGER, BOOLEAN, DATETIME (default: STRING)"},
                "execution_context": {"type": "string", "description": "Run as SYSTEM or USER (default: SYSTEM)"},
            },
            "required": ["og_uuid", "name", "platform", "query_type", "script_content"],
        },
    ),
    Tool(
        name="uem_create_sensor_from_json",
        description=(
            "Create a sensor from a JSON body (same schema returned by uem_get_sensor). "
            "Use this to duplicate or migrate sensors: download with uem_get_sensor, "
            "modify the name or settings, then upload with this tool. "
            "The script_data should remain base64-encoded as returned by uem_get_sensor. "
            "Read-only fields (uuid, is_read_only) are stripped automatically. "
            "Sensor names only allow letters, numbers, periods, underscores, and spaces."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "sensor_json": {"type": "string", "description": "Full sensor JSON body (same schema as uem_get_sensor output)"},
            },
            "required": ["sensor_json"],
        },
    ),
    # -----------------------------------------------------------------------
    # Export tools
    # -----------------------------------------------------------------------
    Tool(
        name="uem_export_all",
        description=(
            "Export all UEM resources from an organization group to disk as a backup. "
            "Saves scripts, sensors, profiles, and app metadata/binaries as JSON files "
            "in a timestamped export directory with a manifest.json. "
            "If group_id is omitted, the top-level OG for the authenticated "
            "account is used automatically. "
            "All fields (including read-only ones) are preserved for reference. "
            "Exported scripts and sensors can be re-imported with "
            "uem_create_script_from_json / uem_create_sensor_from_json. "
            "V2 profiles can be re-imported with uem_create_profile."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "group_id": {"type": "string", "description": "OG group ID code (default: top-level OG for the account)"},
                "output_dir": {"type": "string", "description": "Directory to save the export (default: ~/.wingman-mcp/exports)"},
                "resource_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["scripts", "sensors", "profiles", "apps"]},
                    "description": "Resource types to export (default: all four)",
                },
                "include_app_blobs": {
                    "type": "boolean",
                    "description": "Download app binary blobs (default: true, can be slow for large apps)",
                },
            },
            "required": [],
        },
    ),
    # -----------------------------------------------------------------------
    # Migration tools
    # -----------------------------------------------------------------------
    Tool(
        name="uem_migrate_scripts",
        description=(
            "Migrate all scripts from one UEM environment to another. "
            "Reads every script from the source organization group, then creates them "
            "in the destination organization group in the destination environment. "
            "Skips scripts whose name already exists in the destination. "
            "Returns a summary of migrated, skipped, and failed scripts."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_env": {"type": "string", "description": "Source environment name"},
                "dest_env": {"type": "string", "description": "Destination environment name"},
                "source_og_uuid": {"type": "string", "description": "Source organization group UUID"},
                "dest_og_uuid": {"type": "string", "description": "Destination organization group UUID"},
            },
            "required": ["source_env", "dest_env", "source_og_uuid", "dest_og_uuid"],
        },
    ),
    Tool(
        name="uem_migrate_sensors",
        description=(
            "Migrate all sensors from one UEM environment to another. "
            "Reads every sensor from the source organization group, then creates them "
            "in the destination organization group in the destination environment. "
            "Skips sensors whose name already exists in the destination. "
            "Returns a summary of migrated, skipped, and failed sensors."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_env": {"type": "string", "description": "Source environment name"},
                "dest_env": {"type": "string", "description": "Destination environment name"},
                "source_og_uuid": {"type": "string", "description": "Source organization group UUID"},
                "dest_og_uuid": {"type": "string", "description": "Destination organization group UUID"},
            },
            "required": ["source_env", "dest_env", "source_og_uuid", "dest_og_uuid"],
        },
    ),
    Tool(
        name="uem_migrate_profiles",
        description=(
            "Migrate device profiles from one UEM environment to another. "
            "Reads profiles from the source OG (optionally filtered by platform), "
            "then creates them in the destination OG. Only V2-compatible profiles "
            "can be migrated (Windows: all, Apple/Android: V2 payloads like Custom "
            "Settings, WiFi, VPN, SCEP, SSO Extension, etc.). Non-V2 profiles are "
            "skipped with a warning. Smart group assignments are stripped since "
            "smart group IDs differ between environments."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_env": {"type": "string", "description": "Source environment name"},
                "dest_env": {"type": "string", "description": "Destination environment name"},
                "source_og_id": {"type": "string", "description": "Source organization group numeric ID"},
                "dest_og_id": {"type": "string", "description": "Destination organization group numeric ID"},
                "platform": {"type": "string", "description": "Optional platform filter (Apple, Android, WinRT)"},
            },
            "required": ["source_env", "dest_env", "source_og_id", "dest_og_id"],
        },
    ),
    Tool(
        name="uem_migrate_apps",
        description=(
            "Migrate internal applications from one UEM environment to another. "
            "Downloads each app binary from the source environment, uploads it to "
            "the destination, and creates the app with matching metadata. "
            "Only internal apps can be migrated — public and purchased apps are skipped. "
            "Large apps may take time to transfer."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_env": {"type": "string", "description": "Source environment name"},
                "dest_env": {"type": "string", "description": "Destination environment name"},
                "source_og_id": {"type": "string", "description": "Source organization group numeric ID"},
                "dest_og_id": {"type": "string", "description": "Destination organization group numeric ID"},
            },
            "required": ["source_env", "dest_env", "source_og_id", "dest_og_id"],
        },
    ),
    # -----------------------------------------------------------------------
    # App Volumes API tools (require auth via 'wingman-mcp auth set --product app_volumes')
    # -----------------------------------------------------------------------
    Tool(
        name="app_volumes_search_applications",
        description=(
            "Search Applications in App Volumes Manager. An Application is a "
            "top-level product that contains one or more Packages. "
            "Requires App Volumes credentials configured via "
            "'wingman-mcp auth set --product app_volumes'."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="app_volumes_get_application",
        description="Get details of an App Volumes Application by its ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "app_id": {"type": "string", "description": "Numeric Application ID"},
            },
            "required": ["app_id"],
        },
    ),
    Tool(
        name="app_volumes_search_packages",
        description=(
            "Search Packages in App Volumes Manager. A Package is the actual "
            "delivery payload (a virtual disk) attached to one Application."
        ),
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="app_volumes_get_package",
        description="Get details of an App Volumes Package by its ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "package_id": {"type": "string", "description": "Numeric Package ID"},
            },
            "required": ["package_id"],
        },
    ),
    Tool(
        name="app_volumes_search_writable_volumes",
        description=(
            "Search Writable Volumes in App Volumes Manager. "
            "Filters: volume_guid, user_guid, owner_name, "
            "created_after / updated_after (ISO 8601), "
            "min_capacity / max_capacity (MB), count."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "volume_guid": {"type": "string"},
                "user_guid": {"type": "string"},
                "owner_name": {"type": "string"},
                "created_after": {"type": "string", "description": "ISO 8601 datetime"},
                "updated_after": {"type": "string", "description": "ISO 8601 datetime"},
                "min_capacity": {"type": "integer", "description": "Minimum capacity (MB)"},
                "max_capacity": {"type": "integer", "description": "Maximum capacity (MB)"},
                "count": {"type": "integer", "description": "Limit results"},
            },
            "required": [],
        },
    ),
    Tool(
        name="app_volumes_get_writable_volume",
        description="Get an App Volumes Writable Volume by ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "writable_id": {"type": "string", "description": "Numeric Writable Volume ID"},
            },
            "required": ["writable_id"],
        },
    ),
    Tool(
        name="app_volumes_grow_writable_volume",
        description=(
            "Increase the size of one or more Writable Volumes. "
            "Mutation — non-destructive but irreversible. Pass the volume IDs "
            "to grow and the new size in MB (must exceed current size)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "writable_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "IDs of the Writable Volumes to grow",
                },
                "size_mb": {
                    "type": "integer",
                    "description": "New size in MB (must exceed current size)",
                },
            },
            "required": ["writable_ids", "size_mb"],
        },
    ),
    # -----------------------------------------------------------------------
    # Horizon API tools (require auth via 'wingman-mcp auth set --product horizon')
    # -----------------------------------------------------------------------
    Tool(
        name="horizon_search_desktop_pools",
        description=(
            "List Desktop Pools in a Horizon environment. Supports paging "
            "(page, size) and server-side filter/sort_by/order_by. "
            "Requires Horizon credentials configured via "
            "'wingman-mcp auth set --product horizon'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "page": {"type": "integer"},
                "size": {"type": "integer", "description": "Page size"},
                "filter": {"type": "string", "description": "Horizon filter expression (JSON)"},
                "sort_by": {"type": "string"},
                "order_by": {"type": "string", "description": "ASCENDING or DESCENDING"},
            },
            "required": [],
        },
    ),
    Tool(
        name="horizon_get_desktop_pool",
        description="Get full details of a Horizon Desktop Pool by ID.",
        inputSchema={
            "type": "object",
            "properties": {"pool_id": {"type": "string"}},
            "required": ["pool_id"],
        },
    ),
    Tool(
        name="horizon_search_farms",
        description=(
            "List Farms (RDSH) in a Horizon environment. "
            "Supports page/size/filter/sort_by/order_by."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "page": {"type": "integer"},
                "size": {"type": "integer"},
                "filter": {"type": "string"},
                "sort_by": {"type": "string"},
                "order_by": {"type": "string"},
            },
            "required": [],
        },
    ),
    Tool(
        name="horizon_get_farm",
        description="Get full details of a Horizon Farm by ID.",
        inputSchema={
            "type": "object",
            "properties": {"farm_id": {"type": "string"}},
            "required": ["farm_id"],
        },
    ),
    Tool(
        name="horizon_search_machines",
        description=(
            "List Machines (VMs) in a Horizon environment. "
            "Supports page/size/filter/sort_by/order_by."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "page": {"type": "integer"},
                "size": {"type": "integer"},
                "filter": {"type": "string"},
                "sort_by": {"type": "string"},
                "order_by": {"type": "string"},
            },
            "required": [],
        },
    ),
    Tool(
        name="horizon_get_machine",
        description="Get full details of a Horizon Machine (VM) by ID.",
        inputSchema={
            "type": "object",
            "properties": {"machine_id": {"type": "string"}},
            "required": ["machine_id"],
        },
    ),
    Tool(
        name="horizon_search_sessions",
        description=(
            "List active and disconnected user Sessions in a Horizon environment "
            "(uses the v8 endpoint — latest schema). "
            "Supports page/size/filter/sort_by/order_by."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "page": {"type": "integer"},
                "size": {"type": "integer"},
                "filter": {"type": "string"},
                "sort_by": {"type": "string"},
                "order_by": {"type": "string"},
            },
            "required": [],
        },
    ),
    Tool(
        name="horizon_get_session",
        description="Get full details of a Horizon Session by ID (v8).",
        inputSchema={
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    ),
    Tool(
        name="horizon_disconnect_sessions",
        description=(
            "Disconnect one or more locally-resourced user sessions (mutation). "
            "Disconnect leaves applications running so users can resume — for a "
            "full sign-out, use the Horizon admin console."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Session IDs to disconnect",
                },
            },
            "required": ["session_ids"],
        },
    ),
    Tool(
        name="horizon_restart_machines",
        description=(
            "Restart (reboot) one or more Horizon machines (mutation). "
            "By default the action is rejected if any machine has open "
            "sessions; pass force_operation=true to restart anyway."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "machine_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Machine IDs to restart",
                },
                "force_operation": {
                    "type": "boolean",
                    "description": "Force restart even with active sessions",
                    "default": False,
                },
            },
            "required": ["machine_ids"],
        },
    ),
    # -----------------------------------------------------------------------
    # Identity Service API tools
    # (require auth via 'wingman-mcp auth set --product identity_service')
    # -----------------------------------------------------------------------
    Tool(
        name="identity_service_search_users",
        description=(
            "Search SCIM 2.0 users in an Omnissa Identity Service tenant. "
            "Supports SCIM filter syntax (e.g. filter='userName eq \"alice@x.com\"'), "
            "startIndex/count paging, and sortBy/sortOrder."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "filter": {"type": "string", "description": "SCIM filter expression"},
                "sortBy": {"type": "string"},
                "sortOrder": {"type": "string", "description": "ascending or descending"},
                "startIndex": {"type": "integer", "description": "1-based page start"},
                "count": {"type": "integer", "description": "Page size"},
                "attributes": {"type": "string", "description": "Comma list of attrs to return"},
                "excludedAttributes": {"type": "string"},
            },
            "required": [],
        },
    ),
    Tool(
        name="identity_service_get_user",
        description="Get a SCIM user by ID from an Omnissa Identity Service tenant.",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "attributes": {"type": "string"},
                "excludedAttributes": {"type": "string"},
            },
            "required": ["user_id"],
        },
    ),
    Tool(
        name="identity_service_search_groups",
        description="Search SCIM 2.0 groups in an Omnissa Identity Service tenant.",
        inputSchema={
            "type": "object",
            "properties": {
                "filter": {"type": "string"},
                "sortBy": {"type": "string"},
                "sortOrder": {"type": "string"},
                "startIndex": {"type": "integer"},
                "count": {"type": "integer"},
                "attributes": {"type": "string"},
                "excludedAttributes": {"type": "string"},
            },
            "required": [],
        },
    ),
    Tool(
        name="identity_service_get_group",
        description="Get a SCIM group by ID from an Omnissa Identity Service tenant.",
        inputSchema={
            "type": "object",
            "properties": {
                "group_id": {"type": "string"},
                "attributes": {"type": "string"},
                "excludedAttributes": {"type": "string"},
            },
            "required": ["group_id"],
        },
    ),
    Tool(
        name="identity_service_search_directories",
        description="List the user directories configured in an Identity Service tenant.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="identity_service_get_directory",
        description="Get a directory configuration by ID.",
        inputSchema={
            "type": "object",
            "properties": {"directory_id": {"type": "string"}},
            "required": ["directory_id"],
        },
    ),
    Tool(
        name="identity_service_create_user",
        description=(
            "Create a SCIM 2.0 user in an Omnissa Identity Service tenant (mutation). "
            "Pass the full SCIM user resource — at minimum `schemas`, `userName`, and "
            "`name`/`emails`. The directory the user lands in is determined by the "
            "client's authorization scope."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_resource": {
                    "type": "object",
                    "description": "Full SCIM 2.0 User resource (schemas, userName, name, emails, etc.)",
                },
            },
            "required": ["user_resource"],
        },
    ),
    # -----------------------------------------------------------------------
    # Workspace ONE Access API tools
    # (require auth via 'wingman-mcp auth set --product access')
    # -----------------------------------------------------------------------
    Tool(
        name="access_search_users",
        description=(
            "Search SCIM users in a Workspace ONE Access tenant. Supports SCIM "
            "filter, startIndex/count paging, sortBy/sortOrder, attributes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "filter": {"type": "string"},
                "sortBy": {"type": "string"},
                "sortOrder": {"type": "string"},
                "startIndex": {"type": "integer"},
                "count": {"type": "integer"},
                "attributes": {"type": "string"},
                "customSchemaExtensionTypes": {"type": "string"},
            },
            "required": [],
        },
    ),
    Tool(
        name="access_get_user",
        description="Get a SCIM user by ID from a Workspace ONE Access tenant.",
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "attributes": {"type": "string"},
                "directoryUuid": {"type": "string"},
            },
            "required": ["user_id"],
        },
    ),
    Tool(
        name="access_search_groups",
        description="Search SCIM groups in a Workspace ONE Access tenant.",
        inputSchema={
            "type": "object",
            "properties": {
                "filter": {"type": "string"},
                "sortBy": {"type": "string"},
                "sortOrder": {"type": "string"},
                "startIndex": {"type": "integer"},
                "count": {"type": "integer"},
                "attributes": {"type": "string"},
            },
            "required": [],
        },
    ),
    Tool(
        name="access_get_group",
        description="Get a SCIM group by ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "group_id": {"type": "string"},
                "attributes": {"type": "string"},
            },
            "required": ["group_id"],
        },
    ),
    Tool(
        name="access_search_entitlements",
        description=(
            "Search entitlements (catalog items) in a Workspace ONE Access tenant. "
            "Pass userId to scope to one user, or omit for the authenticated client. "
            "criteria is a SearchCriteria body (pass {} for unrestricted)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "userId": {"type": "string"},
                "showVisibleAppsOnly": {"type": "boolean"},
                "startIndex": {"type": "integer"},
                "pageSize": {"type": "integer"},
                "criteria": {
                    "type": "object",
                    "description": "SearchCriteria body. Pass {} for 'no filter'.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="access_get_activity_summary_report",
        description=(
            "Get the activity summary report for a time interval. "
            "interval values are tenant-version-specific (e.g. 'day', 'week', "
            "'month'); use search_api_reference --product access if unsure."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "interval": {"type": "string"},
            },
            "required": ["interval"],
        },
    ),
    Tool(
        name="access_create_user",
        description=(
            "Create a local user in a Workspace ONE Access tenant (mutation). "
            "user_resource follows the SdkUserResource schema. sendMail=true "
            "triggers a password-setup email."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_resource": {
                    "type": "object",
                    "description": "Full SCIM/SDK user resource.",
                },
                "sendMail": {"type": "boolean"},
                "attributes": {"type": "string"},
            },
            "required": ["user_resource"],
        },
    ),
]

# Inject 'env' parameter into all UEM API tool schemas (except uem_list_environments)
_ENV_PROPERTY = {
    "env": {
        "type": "string",
        "description": (
            "Named environment to use (from 'wingman-mcp auth list'). "
            "Defaults to 'default'."
        ),
    }
}
_SKIP_ENV_INJECTION = {"uem_list_environments", "uem_migrate_scripts",
                       "uem_migrate_sensors", "uem_migrate_profiles",
                       "uem_migrate_apps"}
# Tool-name prefixes that get the per-product `env` parameter injected.
_PRODUCT_TOOL_PREFIXES = ("uem_", "app_volumes_", "horizon_", "identity_service_",
                           "access_")
for _tool in TOOLS:
    if (any(_tool.name.startswith(p) for p in _PRODUCT_TOOL_PREFIXES)
            and _tool.name not in _SKIP_ENV_INJECTION):
        _tool.inputSchema["properties"].update(_ENV_PROPERTY)


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


def _require_auth(env_name: str = "default") -> "UEMAuth":
    """Return a UEMAuth instance or raise with a user-friendly message."""
    auth = _get_auth(env_name)
    if auth is None:
        from wingman_mcp.request_context import _is_http_request
        if _is_http_request.get():
            raise RuntimeError(
                "UEM API credentials not provided. Add the following headers to your "
                "MCP server configuration: X-UEM-Client-ID, X-UEM-Client-Secret, "
                "X-UEM-Token-URL, X-UEM-API-URL."
            )
        raise RuntimeError(
            f"UEM API credentials are not configured for environment '{env_name}'. "
            f"Run 'wingman-mcp auth set --env {env_name}' to provide your Client ID, "
            "Client Secret, Token URL, and API Base URL."
        )
    return auth


# ---------------------------------------------------------------------------
# Per-product (non-UEM) tool dispatch
# ---------------------------------------------------------------------------

# Each entry: tool_name → (product_slug, function, positional_keys)
_PRODUCT_API_TOOLS: dict[str, tuple[str, Any, Optional[list[str]]]] = {}


def _build_product_client(product: str, env_name: str):
    """Construct a product API client from stored credentials.

    Returns the client or raises RuntimeError with a user-friendly message.
    """
    from wingman_mcp.credentials import load_product_credentials

    creds = load_product_credentials(product, env_name)
    if creds is None:
        raise RuntimeError(
            f"{product} credentials are not configured for environment "
            f"'{env_name}'. Run 'wingman-mcp auth set --product {product} "
            f"--env {env_name}' to provide them."
        )
    if product == "app_volumes":
        from wingman_mcp.app_volumes_api import AppVolumesClient
        return AppVolumesClient(
            manager_url=creds["manager_url"],
            username=creds["username"],
            password=creds["password"],
        )
    if product == "horizon":
        from wingman_mcp.horizon_api import HorizonClient
        return HorizonClient(
            server_url=creds["server_url"],
            username=creds["username"],
            password=creds["password"],
            domain=creds["domain"],
        )
    if product == "identity_service":
        from wingman_mcp.identity_service_api import IdentityServiceClient
        return IdentityServiceClient(
            tenant_url=creds["tenant_url"],
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            token_url=creds.get("token_url") or None,
        )
    if product == "access":
        from wingman_mcp.access_api import AccessClient
        return AccessClient(
            tenant_url=creds["tenant_url"],
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
            token_url=creds.get("token_url") or None,
        )
    raise RuntimeError(f"No client implementation registered for product '{product}'.")


def _get_product_client(product: str, env_name: str = "default"):
    key = (product, env_name)
    if key not in _product_clients:
        _product_clients[key] = _build_product_client(product, env_name)
    return _product_clients[key]


def _register_product_api_tools() -> None:
    """Build the dispatch table for non-UEM product API tools."""
    from wingman_mcp import app_volumes_api as av
    from wingman_mcp import horizon_api as hz
    from wingman_mcp import identity_service_api as ids
    from wingman_mcp import access_api as acc

    _PRODUCT_API_TOOLS.update({
        # App Volumes
        "app_volumes_search_applications":     ("app_volumes", av.search_applications, None),
        "app_volumes_get_application":         ("app_volumes", av.get_application, ["app_id"]),
        "app_volumes_search_packages":         ("app_volumes", av.search_packages, None),
        "app_volumes_get_package":             ("app_volumes", av.get_package, ["package_id"]),
        "app_volumes_search_writable_volumes": ("app_volumes", av.search_writable_volumes, None),
        "app_volumes_get_writable_volume":     ("app_volumes", av.get_writable_volume, ["writable_id"]),
        "app_volumes_grow_writable_volume":    ("app_volumes", av.grow_writable_volume, ["writable_ids", "size_mb"]),
        # Horizon
        "horizon_search_desktop_pools":  ("horizon", hz.search_desktop_pools, None),
        "horizon_get_desktop_pool":      ("horizon", hz.get_desktop_pool, ["pool_id"]),
        "horizon_search_farms":          ("horizon", hz.search_farms, None),
        "horizon_get_farm":              ("horizon", hz.get_farm, ["farm_id"]),
        "horizon_search_machines":       ("horizon", hz.search_machines, None),
        "horizon_get_machine":           ("horizon", hz.get_machine, ["machine_id"]),
        "horizon_search_sessions":       ("horizon", hz.search_sessions, None),
        "horizon_get_session":           ("horizon", hz.get_session, ["session_id"]),
        "horizon_disconnect_sessions":   ("horizon", hz.disconnect_sessions, ["session_ids"]),
        "horizon_restart_machines":      ("horizon", hz.restart_machines, ["machine_ids"]),
        # Identity Service
        "identity_service_search_users":       ("identity_service", ids.search_users, None),
        "identity_service_get_user":           ("identity_service", ids.get_user, ["user_id"]),
        "identity_service_search_groups":      ("identity_service", ids.search_groups, None),
        "identity_service_get_group":          ("identity_service", ids.get_group, ["group_id"]),
        "identity_service_search_directories": ("identity_service", ids.search_directories, None),
        "identity_service_get_directory":      ("identity_service", ids.get_directory, ["directory_id"]),
        "identity_service_create_user":        ("identity_service", ids.create_user, ["user_resource"]),
        # Workspace ONE Access
        "access_search_users":                  ("access", acc.search_users, None),
        "access_get_user":                      ("access", acc.get_user, ["user_id"]),
        "access_search_groups":                 ("access", acc.search_groups, None),
        "access_get_group":                     ("access", acc.get_group, ["group_id"]),
        "access_search_entitlements":           ("access", acc.search_entitlements, None),
        "access_get_activity_summary_report":   ("access", acc.get_activity_summary_report, ["interval"]),
        "access_create_user":                   ("access", acc.create_user, ["user_resource"]),
    })


# Map of API tool names to (function, argument keys)
_API_TOOLS: dict[str, tuple] = {}


def _register_api_tools():
    """Build the dispatch table for UEM API tools."""
    from wingman_mcp import uem_api
    from wingman_mcp import export

    _API_TOOLS.update({
        "uem_search_devices": (uem_api.search_devices, None),
        "uem_get_device": (uem_api.get_device, ["device_id"]),
        "uem_get_device_profiles": (uem_api.get_device_profiles, ["device_id"]),
        "uem_get_device_apps": (uem_api.get_device_apps, ["device_id"]),
        "uem_get_device_security": (uem_api.get_device_security, ["device_id"]),
        "uem_get_device_network": (uem_api.get_device_network, ["device_id"]),
        "uem_send_device_command": (uem_api.send_device_command, ["device_id", "command"]),
        "uem_search_users": (uem_api.search_users, None),
        "uem_get_user": (uem_api.get_user, ["user_id"]),
        "uem_search_organization_groups": (uem_api.search_organization_groups, None),
        "uem_get_organization_group": (uem_api.get_organization_group, ["og_id"]),
        "uem_get_og_children": (uem_api.get_og_children, ["og_id"]),
        "uem_search_smart_groups": (uem_api.search_smart_groups, None),
        "uem_search_profiles": (uem_api.search_profiles, None),
        "uem_get_profile": (uem_api.get_profile, ["profile_id"]),
        "uem_search_compliance_policies": (uem_api.search_compliance_policies, None),
        "uem_get_baseline_templates": (uem_api.get_baseline_templates, None),
        "uem_search_baseline_policies": (uem_api.search_baseline_policies, ["os_version_uuid"]),
        "uem_get_baseline_policy": (uem_api.get_baseline_policy, ["policy_uuid"]),
        "uem_search_apps": (uem_api.search_apps, None),
        "uem_get_app": (uem_api.get_app, ["app_id"]),
        "uem_download_app_blob": (uem_api.download_app_blob, ["blob_uuid", "output_dir"]),
        "uem_create_profile": (uem_api.create_profile, ["platform", "profile_json"]),
        "uem_search_scripts": (uem_api.search_scripts, ["og_uuid"]),
        "uem_get_script": (uem_api.get_script, ["script_uuid"]),
        "uem_search_sensors": (uem_api.search_sensors, ["og_uuid"]),
        "uem_get_sensor": (uem_api.get_sensor, ["sensor_uuid"]),
        "uem_create_script": (uem_api.create_script, ["og_uuid"]),
        "uem_create_script_from_json": (uem_api.create_script_from_json, ["script_json"]),
        "uem_create_sensor": (uem_api.create_sensor, ["og_uuid"]),
        "uem_create_sensor_from_json": (uem_api.create_sensor_from_json, ["sensor_json"]),
        "uem_export_all": (export.export_all, None),
    })


# Migration tool names
_MIGRATION_TOOLS = {
    "uem_migrate_scripts",
    "uem_migrate_sensors",
    "uem_migrate_profiles",
    "uem_migrate_apps",
}


def _handle_migration(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch migration tool calls."""
    from wingman_mcp import migration

    source_env = arguments["source_env"]
    dest_env = arguments["dest_env"]

    try:
        source_auth = _require_auth(source_env)
        dest_auth = _require_auth(dest_env)
    except RuntimeError as e:
        return [TextContent(type="text", text=str(e))]

    try:
        if name == "uem_migrate_scripts":
            result = migration.migrate_scripts(
                source_auth, dest_auth,
                arguments["source_og_uuid"], arguments["dest_og_uuid"],
            )
        elif name == "uem_migrate_sensors":
            result = migration.migrate_sensors(
                source_auth, dest_auth,
                arguments["source_og_uuid"], arguments["dest_og_uuid"],
            )
        elif name == "uem_migrate_profiles":
            result = migration.migrate_profiles(
                source_auth, dest_auth,
                arguments["source_og_id"], arguments["dest_og_id"],
                platform=arguments.get("platform"),
            )
        elif name == "uem_migrate_apps":
            result = migration.migrate_apps(
                source_auth, dest_auth,
                arguments["source_og_id"], arguments["dest_og_id"],
            )
        else:
            return [TextContent(type="text", text=f"Unknown migration tool: {name}")]

        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=f"Migration error: {e}")]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    # --- RAG search tools ---
    if name in ("search_uem_docs", "search_api_reference", "search_release_notes",
                "search_omnissa_docs"):
        if name == "search_uem_docs":
            if not stores_exist():
                return [TextContent(
                    type="text",
                    text="RAG stores not found. Run 'wingman-mcp ingest' to build them, "
                         "or 'wingman-mcp setup' to download pre-built stores.",
                )]
            results = search_uem(
                query=arguments["query"],
                db=_get_store("uem"),
                max_results=arguments.get("max_results", 10),
            )
        elif name == "search_api_reference":
            results = search_api(
                query=arguments["query"],
                db=_get_store("api"),
                product=arguments.get("product", "uem"),
                max_results=arguments.get("max_results", 10),
            )
        elif name == "search_release_notes":
            results = search_release_notes(
                query=arguments["query"],
                db=_get_store("release_notes"),
                version=arguments.get("version"),
                product=arguments.get("product", "uem"),
                max_results=arguments.get("max_results", 15),
            )
        else:  # search_omnissa_docs
            from wingman_mcp.ingest.products import PRODUCTS
            product_slug = arguments.get("product")
            if product_slug not in PRODUCTS:
                return [TextContent(
                    type="text",
                    text=f"Unknown product '{product_slug}'. Valid: {', '.join(PRODUCTS)}",
                )]
            from pathlib import Path
            store_path = Path(get_store_dir(product_slug))
            if not (store_path / "chroma.sqlite3").exists():
                return [TextContent(
                    type="text",
                    text=f"Store for product '{product_slug}' has not been built. "
                         f"Run: wingman-mcp ingest {product_slug}",
                )]
            cfg = PRODUCTS[product_slug]
            # Route the UEM slug through the multi-family scorer for parity
            # with `search_uem_docs`.
            if product_slug == "uem":
                results = search_uem(
                    query=arguments["query"],
                    db=_get_store("uem"),
                    max_results=arguments.get("max_results", 10),
                )
            else:
                results = search_product_docs(
                    query=arguments["query"],
                    db=_get_store(product_slug),
                    search_prefix=cfg.search_prefix,
                    max_results=arguments.get("max_results", 10),
                )

        if not results:
            return [TextContent(type="text", text="No results found.")]
        return [TextContent(type="text", text=json.dumps(results, indent=2))]

    # --- UEM list environments (no auth required) ---
    if name == "uem_list_environments":
        from wingman_mcp.credentials import list_environments, get_status
        envs = list_environments()
        result = {
            "environments": envs,
            "count": len(envs),
            "details": {e: get_status(e) for e in envs},
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    # --- UEM API tools ---
    if not _API_TOOLS:
        _register_api_tools()

    # --- UEM migration tools ---
    if name in _MIGRATION_TOOLS:
        return _handle_migration(name, arguments)

    if name in _API_TOOLS:
        # Extract env from arguments (don't pass it to the API function)
        env_name = arguments.pop("env", "default")
        try:
            auth = _require_auth(env_name)
        except RuntimeError as e:
            return [TextContent(type="text", text=str(e))]

        func, positional_keys = _API_TOOLS[name]
        try:
            if positional_keys:
                pos_args = [arguments[k] for k in positional_keys]
                kwargs = {k: v for k, v in arguments.items() if k not in positional_keys}
                result = func(auth, *pos_args, **kwargs)
            else:
                result = func(auth, **arguments)
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        except Exception as e:
            return [TextContent(type="text", text=f"API error: {e}")]

    # --- Non-UEM product API tools ---
    if not _PRODUCT_API_TOOLS:
        _register_product_api_tools()

    if name in _PRODUCT_API_TOOLS:
        product, func, positional_keys = _PRODUCT_API_TOOLS[name]
        env_name = arguments.pop("env", "default")
        try:
            client = _get_product_client(product, env_name)
        except RuntimeError as e:
            return [TextContent(type="text", text=str(e))]

        try:
            if positional_keys:
                pos_args = [arguments[k] for k in positional_keys]
                kwargs = {k: v for k, v in arguments.items() if k not in positional_keys}
                result = func(client, *pos_args, **kwargs)
            else:
                result = func(client, **arguments)
            return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
        except Exception as e:
            # On auth failures, drop the cached client so the next call re-logs in.
            if "401" in str(e) or "403" in str(e):
                _product_clients.pop((product, env_name), None)
            return [TextContent(type="text", text=f"{product} API error: {e}")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run_server():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


async def run_http_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the MCP server over Streamable HTTP for hosted/cloud deployments.

    Each user's UEM credentials are passed via request headers and are never
    stored server-side.  The server acts as a stateless proxy.

    Required dependencies: pip install 'wingman-mcp[cloud]'
    """
    try:
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.responses import JSONResponse, PlainTextResponse
        from starlette.types import ASGIApp, Receive, Scope, Send
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            f"HTTP mode requires additional dependencies: {exc}\n"
            "Install with: pip install 'wingman-mcp[cloud]'"
        ) from exc

    from wingman_mcp.middleware import CredentialHeaderMiddleware

    session_manager = StreamableHTTPSessionManager(
        app=app,
        event_store=None,
        json_response=False,
        stateless=True,
    )

    class _App:
        """Minimal ASGI app: routes /health and /mcp."""
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "lifespan":
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                msg = await receive()
                if msg["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
            elif scope["type"] == "http":
                if scope["path"] == "/health":
                    resp = PlainTextResponse("ok")
                    await resp(scope, receive, send)
                else:
                    await session_manager.handle_request(scope, receive, send)

    asgi_app = CredentialHeaderMiddleware(_App())

    print(f"wingman-mcp HTTP server starting on {host}:{port}")
    print(f"MCP endpoint : http://{host}:{port}/mcp")
    print(f"Health check : http://{host}:{port}/health")

    config = uvicorn.Config(asgi_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    async with session_manager.run():
        await server.serve()
