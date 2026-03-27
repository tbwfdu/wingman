"""MCP server exposing Workspace ONE UEM documentation search tools."""
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from wingman_mcp.config import get_store_dir, stores_exist, STORE_KEYS
from wingman_mcp.search import search_uem, search_api, search_release_notes

app = Server("wingman-mcp")

# Lazy-loaded stores and auth
_stores: dict[str, Any] = {}
_embeddings = None
_auth = None


def _get_embeddings():
    global _embeddings
    if _embeddings is None:
        from wingman_mcp.embeddings import LocalEmbeddings
        _embeddings = LocalEmbeddings()
    return _embeddings


def _get_auth():
    """Return a UEMAuth instance if credentials are configured, else None."""
    global _auth
    if _auth is None:
        from wingman_mcp.credentials import load_credentials
        creds = load_credentials()
        if creds is None:
            return None
        from wingman_mcp.auth import UEMAuth
        _auth = UEMAuth(creds)
    return _auth


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
            "Search Workspace ONE UEM REST API endpoint documentation. "
            "Covers MDM, MAM, MCM, MEM, and System API groups. "
            "Returns endpoint details: method, path, summary, parameters. "
            "Use this when the user asks about API calls, endpoints, or programmatic access."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query about UEM APIs (e.g. 'enroll device', 'GET profiles')",
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
        name="search_release_notes",
        description=(
            "Search Workspace ONE UEM release notes for feature changes, "
            "bug fixes, resolved issues, and new capabilities across versions. "
            "Supports version filtering (e.g. '2602', '2509', '2506'). "
            "Use this when the user asks about what's new, version changes, or resolved issues."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query about release notes or version changes",
                },
                "version": {
                    "type": "string",
                    "description": "Optional version filter (e.g. '2602', '2509', '2506')",
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
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


def _require_auth() -> "UEMAuth":
    """Return a UEMAuth instance or raise with a user-friendly message."""
    auth = _get_auth()
    if auth is None:
        raise RuntimeError(
            "UEM API credentials are not configured. "
            "Run 'wingman-mcp auth set' to provide your Client ID, Client Secret, "
            "Token URL, and API Base URL."
        )
    return auth


# Map of API tool names to (function, argument keys)
_API_TOOLS: dict[str, tuple] = {}


def _register_api_tools():
    """Build the dispatch table for UEM API tools."""
    from wingman_mcp import uem_api

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
        "uem_search_apps": (uem_api.search_apps, None),
    })


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    # --- RAG search tools ---
    if name in ("search_uem_docs", "search_api_reference", "search_release_notes"):
        if not stores_exist():
            return [TextContent(
                type="text",
                text="RAG stores not found. Run 'wingman-mcp ingest' to build them, "
                     "or 'wingman-mcp setup' to download pre-built stores.",
            )]

        if name == "search_uem_docs":
            results = search_uem(
                query=arguments["query"],
                db=_get_store("uem"),
                max_results=arguments.get("max_results", 10),
            )
        elif name == "search_api_reference":
            results = search_api(
                query=arguments["query"],
                db=_get_store("api"),
                max_results=arguments.get("max_results", 10),
            )
        else:
            results = search_release_notes(
                query=arguments["query"],
                db=_get_store("release_notes"),
                version=arguments.get("version"),
                max_results=arguments.get("max_results", 15),
            )

        if not results:
            return [TextContent(type="text", text="No results found.")]
        return [TextContent(type="text", text=json.dumps(results, indent=2))]

    # --- UEM API tools ---
    if not _API_TOOLS:
        _register_api_tools()

    if name in _API_TOOLS:
        try:
            auth = _require_auth()
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

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def run_server():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())
