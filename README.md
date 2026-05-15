# wingman-mcp

> Wingman: your AI sidekick for Omnissa EUC. Documentation, APIs, and release notes for UEM, Horizon, App Volumes, Access, Identity Service, and more, plus live API access, all one question away from your editor or AI chat app.

A local [Model Context Protocol](https://modelcontextprotocol.io) server that runs entirely on your machine. It provides Omnissa product documentation search via a local RAG index and live API access to Workspace ONE UEM, Horizon, App Volumes, Workspace ONE Access, Omnissa Identity Service, and Horizon Cloud Service.

Everything runs in a local `wingman-mcp` process over stdio. Documentation search needs no credentials; the live API tools use credentials you store in your own OS keychain. Nothing is sent to any hosted service.

Exposes 82 tools:

### Documentation search (local RAG, no auth required)

| Tool | Description |
|------|-------------|
| `search_uem_docs` | Workspace ONE UEM product documentation (multi-family scoring) |
| `search_omnissa_docs` | Per-product docs for any of the 20+ Omnissa product slugs (Horizon, App Volumes, UAG, DEM, Access, Intelligence, Identity Service, ThinApp, TechZone, and more) |
| `search_api_reference` | REST API endpoint reference; pass `product` to scope to UEM, Horizon, Horizon Cloud, App Volumes, UAG, Access, Intelligence, or Identity Service |
| `search_release_notes` | Release notes by version, scoped per product |

### Live product APIs (require auth; see [Authentication](#authentication) below)

#### UEM: Environments

| Tool | Description |
|------|-------------|
| `uem_list_environments` | List all configured UEM environments and their connection status |

#### UEM: Devices

| Tool | Description |
|------|-------------|
| `uem_search_devices` | Search/filter managed devices by user, platform, model, compliance, ownership |
| `uem_get_device` | Get full device details by device ID |
| `uem_get_device_profiles` | List profiles installed on a device |
| `uem_get_device_apps` | List apps installed on a device |
| `uem_get_device_security` | Device security info (encryption, passcode, compromised status) |
| `uem_get_device_network` | Device network info (IPs, MAC, WiFi, cellular) |
| `uem_send_device_command` | Send commands to a device (DeviceQuery, Lock, EnterpriseWipe, etc.) |

#### UEM: Users & Organization Groups

| Tool | Description |
|------|-------------|
| `uem_search_users` | Search enrollment users by name, email, username |
| `uem_get_user` | Get enrollment user details by user ID |
| `uem_search_organization_groups` | Search organization groups (OGs) |
| `uem_get_organization_group` | Get OG details by ID |
| `uem_get_og_children` | List child OGs under a parent |
| `uem_search_smart_groups` | Search smart groups |

#### UEM: Profiles

| Tool | Description |
|------|-------------|
| `uem_search_profiles` | Search device profiles by name, platform, status |
| `uem_get_profile` | Get full profile details by ID (V2 round-trip or metadata-transforms fallback) |
| `uem_create_profile` | Create a profile from V2 JSON (Windows all payloads; Apple/Android V2 payloads) |

#### UEM: Scripts

| Tool | Description |
|------|-------------|
| `uem_search_scripts` | List all scripts for an organization group |
| `uem_get_script` | Get full script details by UUID (including base64 script data) |
| `uem_create_script` | Create a script from individual parameters (name, platform, script content) |
| `uem_create_script_from_json` | Create a script from JSON (round-trip from `uem_get_script`) |

#### UEM: Sensors

| Tool | Description |
|------|-------------|
| `uem_search_sensors` | List all sensors for an organization group |
| `uem_get_sensor` | Get full sensor details by UUID (including base64 script data) |
| `uem_create_sensor` | Create a sensor from individual parameters (name, platform, script content) |
| `uem_create_sensor_from_json` | Create a sensor from JSON (round-trip from `uem_get_sensor`) |

#### UEM: Applications

| Tool | Description |
|------|-------------|
| `uem_search_apps` | Search applications by name, bundle ID, platform |
| `uem_get_app` | Get full app details by ID (includes blob GUID and original filename) |
| `uem_download_app_blob` | Download an application binary to disk |

#### UEM: Compliance & Security Baselines

| Tool | Description |
|------|-------------|
| `uem_search_compliance_policies` | Search compliance policies by organization group |
| `uem_get_baseline_templates` | List security baseline vendor templates (Microsoft, CIS) and OS versions |
| `uem_search_baseline_policies` | Browse GPO policies in a baseline catalog version |
| `uem_get_baseline_policy` | Get full details of a baseline policy by UUID |

#### UEM: Export (backup)

| Tool | Description |
|------|-------------|
| `uem_export_all` | Export all resources (scripts, sensors, profiles, apps) from an OG to disk |

Exports create a timestamped directory with a `manifest.json` and individual JSON files for each resource. App binaries are optionally downloaded alongside metadata. All fields (including read-only ones) are preserved. Exported resources can be re-imported using the `create_*_from_json` tools.

#### UEM: Migration (cross-environment)

| Tool | Description |
|------|-------------|
| `uem_migrate_scripts` | Migrate all scripts from one UEM environment/OG to another |
| `uem_migrate_sensors` | Migrate all sensors from one UEM environment/OG to another |
| `uem_migrate_profiles` | Migrate V2-compatible profiles between environments (with optional platform filter) |
| `uem_migrate_apps` | Migrate internal applications (including binaries) between environments |

Migration tools require two named environments to be configured (source and destination). They skip resources that already exist in the destination by name. Smart group assignments are stripped from profiles since IDs differ between environments.

#### App Volumes

Session-cookie auth against an App Volumes Manager. Configure with `wingman-mcp auth set --product app_volumes`.

| Tool | Description |
|------|-------------|
| `app_volumes_search_applications` | List Applications (top-level products that contain Packages) |
| `app_volumes_get_application` | Get details of an Application by ID |
| `app_volumes_search_packages` | List Packages (the deliverable virtual disks) |
| `app_volumes_get_package` | Get details of a Package by ID |
| `app_volumes_search_writable_volumes` | Search Writable Volumes by GUID, owner, capacity, or date |
| `app_volumes_get_writable_volume` | Get a Writable Volume by ID |
| `app_volumes_grow_writable_volume` | Grow one or more Writable Volumes to a new size in MB *(mutation)* |

#### Horizon (Connection Server)

Bearer-token auth against a Horizon Connection Server. Configure with `wingman-mcp auth set --product horizon`.

| Tool | Description |
|------|-------------|
| `horizon_search_desktop_pools` | List desktop pools (paged, filterable) |
| `horizon_get_desktop_pool` | Get a desktop pool by ID |
| `horizon_search_farms` | List farms (RDSH) |
| `horizon_get_farm` | Get a farm by ID |
| `horizon_search_machines` | List machines (VMs) |
| `horizon_get_machine` | Get a machine by ID |
| `horizon_search_sessions` | List active and disconnected user sessions (v8 schema) |
| `horizon_get_session` | Get a session by ID |
| `horizon_disconnect_sessions` | Disconnect one or more user sessions *(mutation)* |
| `horizon_restart_machines` | Restart (reboot) one or more machines, optional `force_operation` *(mutation)* |

#### Workspace ONE Access

OAuth client-credentials auth on a per-tenant URL. Configure with `wingman-mcp auth set --product access`.

| Tool | Description |
|------|-------------|
| `access_search_users` | Search SCIM users (filter, startIndex/count, sortBy/sortOrder) |
| `access_get_user` | Get a SCIM user by ID |
| `access_search_groups` | Search SCIM groups |
| `access_get_group` | Get a SCIM group by ID |
| `access_search_entitlements` | Search catalog-item entitlements per user or for the authenticated client |
| `access_get_activity_summary_report` | Get the activity summary report for a time interval |
| `access_create_user` | Create a local user, optionally sending a setup email *(mutation)* |

#### Omnissa Identity Service

OAuth client-credentials auth on a per-tenant URL. Configure with `wingman-mcp auth set --product identity_service`.

| Tool | Description |
|------|-------------|
| `identity_service_search_users` | Search SCIM 2.0 users (full SCIM filter syntax) |
| `identity_service_get_user` | Get a SCIM user by ID |
| `identity_service_search_groups` | Search SCIM 2.0 groups |
| `identity_service_get_group` | Get a SCIM group by ID |
| `identity_service_search_directories` | List configured directories |
| `identity_service_get_directory` | Get a directory by ID |
| `identity_service_create_user` | Create a SCIM 2.0 user *(mutation)* |

#### Horizon Cloud Service (Next-Gen), read-only

OAuth client-credentials auth against the regional cloud URL (`cloud-sg.horizon.omnissa.com`, etc.). `org_id` is auto-attached on every request. Configure with `wingman-mcp auth set --product horizon_cloud`.

| Tool | Description |
|------|-------------|
| `horizon_cloud_search_pools` | List pool groups |
| `horizon_cloud_get_pool` | Get a pool group by ID |
| `horizon_cloud_search_templates` | List templates (golden images) |
| `horizon_cloud_get_template` | Get a template by ID |
| `horizon_cloud_search_sessions` | Filter active user sessions across pools |
| `horizon_cloud_search_edge_deployments` | List Edge deployments (per-site control plane) |
| `horizon_cloud_get_edge_deployment` | Get an Edge deployment by ID |
| `horizon_cloud_search_active_directories` | List configured AD / domain integrations |
| `horizon_cloud_search_uag_deployments` | List Unified Access Gateway deployments |
| `horizon_cloud_search_sso_configurations` | List SSO / identity-provider configurations |

Mutations on Horizon Cloud (provisioning, batch VM actions, deployment lifecycle) are intentionally not exposed; reach them via `search_api_reference --product horizon_cloud` if you need them.

## Prerequisites

- Python 3.10 or newer

## Setup

### 1. Install the package

Install with the `rag` extra, which pulls in the local embedding and vector-store dependencies needed for documentation search:

```bash
pip install "wingman-mcp[rag]"
```

To install from a source checkout instead:

```bash
git clone https://github.com/<your-org>/wingman-mcp.git
cd wingman-mcp
pip install ".[rag]"
```

> **Multiple Python versions?** If you have more than one Python version installed (via pyenv, Homebrew, system Python, etc.), make sure you install with Python 3.10+. See [Installing with multiple Python versions](#installing-with-multiple-python-versions) below.

### 2. Find the binary path

After installing, find the full path to the `wingman-mcp` binary; you will need it for client configuration:

```bash
which wingman-mcp
```

Example output:

```
/Users/you/.pyenv/versions/3.12.4/bin/wingman-mcp       # pyenv
/Users/you/.venvs/wingman/bin/wingman-mcp                # venv
/Users/you/miniconda3/envs/wingman/bin/wingman-mcp       # conda
/opt/homebrew/bin/wingman-mcp                            # Homebrew Python
/usr/local/bin/wingman-mcp                               # system pip
```

> **Tip:** If `which wingman-mcp` returns nothing, the install location is not on your PATH. Use `find` or `pip show` to locate it; see [Troubleshooting](#troubleshooting).

Use the full path as the `command` in your MCP client configuration to avoid PATH issues. For example, instead of `"command": "wingman-mcp"`, use `"command": "/Users/you/.pyenv/versions/3.12.4/bin/wingman-mcp"`.

### 3. Place the RAG stores

Documentation search reads from pre-built vector stores. Download the store archives from the project's Releases page and extract them into `~/.wingman-mcp/stores/` (the default location):

```bash
mkdir -p ~/.wingman-mcp/stores
unzip -d ~/.wingman-mcp/stores stores_uem-<version>.zip
unzip -d ~/.wingman-mcp/stores stores_api-<version>.zip
unzip -d ~/.wingman-mcp/stores stores_release_notes-<version>.zip
```

Each archive extracts to its own subdirectory (`stores/uem/`, `stores/api/`, `stores/release_notes/`), so they do not collide. To keep the stores somewhere else, set an environment variable instead:

```bash
export WINGMAN_MCP_DATA_DIR=/path/to/stores
```

### 4. Verify

```bash
wingman-mcp status
```

You should see the installed stores listed with their sizes.

### Stores

Each Omnissa product has its own documentation store. Two combined stores,
keyed by `product` metadata, hold release notes and API references.

| Slug | Store |
|---|---|
| `uem` | Workspace ONE UEM (UEM, Hub) |
| `horizon` | Omnissa Horizon |
| `horizon_cloud` | Horizon Cloud Service / DaaS |
| `app_volumes` | App Volumes |
| `uag` | Unified Access Gateway |
| `thinapp` | ThinApp |
| `dem` | Dynamic Environment Manager |
| `access` | Workspace ONE Access |
| `intelligence` | Workspace ONE Intelligence |
| `identity_service` | Omnissa Identity Service |
| `mtd` | Workspace ONE Mobile Threat Defense |
| `servicenow` | Workspace ONE ServiceNow Integration |
| `hub_services` | Workspace ONE Hub Services |
| `xr_hub` | Workspace ONE XR Hub |
| `pivd_manager` | Workspace ONE PIV-D Manager |
| `admin_assistant` | Workspace ONE Admin Assistant |
| `ens` | Workspace ONE Email Notification Service |
| `seg` | Workspace ONE Secure Email Gateway |
| `okta_scim` | Workspace ONE Okta SCIM Provisioning |
| `techzone` | Omnissa TechZone |
| `aw_cloud_connector` | AirWatch Cloud Connector |

Two combined stores:

| Slug | Store |
|---|---|
| `release_notes` (or `<slug>_rn`) | Release notes across all products that publish them, filterable by product |
| `api` (or `<slug>_api`) | REST API references for Horizon, Horizon Cloud, App Volumes, UAG, Access, Intelligence, and Identity Service |

## Client configuration

The server uses **stdio** transport, which is supported by all MCP-compatible clients. The command to start the server is:

```
wingman-mcp serve
```

> **Full path recommended:** MCP clients launch the server as a subprocess without your shell profile, so pyenv/conda/venv may not be active. Use the full binary path from `which wingman-mcp` (e.g. `"/Users/you/.venvs/wingman/bin/wingman-mcp"`) to avoid "command not found" errors.

If you placed the stores in the default location (`~/.wingman-mcp/stores/`), no `env` block is needed. If you placed them elsewhere, add the `WINGMAN_MCP_DATA_DIR` env variable as shown below.

### Codex

```bash
codex mcp add wingman -- wingman-mcp serve
```

If your stores are not in the default location, include the environment variable when adding it:

```bash
codex mcp add wingman --env WINGMAN_MCP_DATA_DIR=/path/to/stores -- wingman-mcp serve
```

You can also add it directly to `~/.codex/config.toml`:

```toml
[mcp_servers.wingman]
command = "wingman-mcp"
args = ["serve"]

[mcp_servers.wingman.env]
WINGMAN_MCP_DATA_DIR = "/path/to/stores"
```

If you are using the default store location, you can omit the `[mcp_servers.wingman.env]` block.

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "wingman": {
      "command": "wingman-mcp",
      "args": ["serve"],
      "env": {
        "WINGMAN_MCP_DATA_DIR": "/path/to/stores"
      }
    }
  }
}
```

### Claude Code

```bash
claude mcp add wingman --scope user -- wingman-mcp serve
```

Or add it manually to `~/.claude.json` under the top-level `mcpServers` key:

```json
{
  "mcpServers": {
    "wingman": {
      "command": "wingman-mcp",
      "args": ["serve"],
      "env": {
        "WINGMAN_MCP_DATA_DIR": "/path/to/stores"
      }
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json` in your project root or `~/.cursor/mcp.json` globally:

```json
{
  "mcpServers": {
    "wingman": {
      "command": "wingman-mcp",
      "args": ["serve"],
      "env": {
        "WINGMAN_MCP_DATA_DIR": "/path/to/stores"
      }
    }
  }
}
```

### Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "wingman": {
      "command": "wingman-mcp",
      "args": ["serve"],
      "env": {
        "WINGMAN_MCP_DATA_DIR": "/path/to/stores"
      }
    }
  }
}
```

### VS Code (Copilot)

Add to `.vscode/mcp.json` in your project root:

```json
{
  "servers": {
    "wingman": {
      "type": "stdio",
      "command": "wingman-mcp",
      "args": ["serve"],
      "env": {
        "WINGMAN_MCP_DATA_DIR": "/path/to/stores"
      }
    }
  }
}
```

### Cline

Add to Cline MCP settings (`cline_mcp_settings.json`):

```json
{
  "mcpServers": {
    "wingman": {
      "command": "wingman-mcp",
      "args": ["serve"],
      "env": {
        "WINGMAN_MCP_DATA_DIR": "/path/to/stores"
      }
    }
  }
}
```

### Any MCP client (generic)

The server speaks MCP over stdio. Start it with:

```bash
WINGMAN_MCP_DATA_DIR=/path/to/stores wingman-mcp serve
```

Connect any MCP client to its stdin/stdout.

## Authentication

The live API tools connect to your Omnissa product environments using each product's native auth flow. Authentication is optional; the RAG documentation search tools work without it.

Each `wingman-mcp auth` command takes `--product <slug>` (default `uem`) and `--env <name>` (default `default`).

### Supported products and credential fields

| Product | `--product` slug | Auth flow | Required fields |
|---|---|---|---|
| Workspace ONE UEM | `uem` | OAuth client credentials | `client_id`, `client_secret`, `token_url`, `api_base_url` |
| Horizon (Connection Server) | `horizon` | Session login (returns JWT) | `username`, `password`, `server_url`, `domain` |
| Horizon Cloud Service | `horizon_cloud` | OAuth client credentials | `client_id`, `client_secret`, `api_base_url`, `org_id` |
| App Volumes | `app_volumes` | Session cookie login | `username`, `password`, `manager_url` |
| Workspace ONE Access | `access` | OAuth client credentials | `client_id`, `client_secret`, `tenant_url`, `token_url` |
| Omnissa Identity Service | `identity_service` | OAuth client credentials | `client_id`, `client_secret`, `tenant_url`, `token_url` |

Secrets (passwords, client secrets) are stored in your OS keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service). Non-secret config (URLs, domain, org_id) is stored in `~/.wingman-mcp/config.json`. Nothing is sent anywhere except directly to the product environment you configured.

### Configure credentials

```bash
# Default product is uem; these two lines are equivalent
wingman-mcp auth set
wingman-mcp auth set --product uem

# Configure a different product
wingman-mcp auth set --product horizon
wingman-mcp auth set --product app_volumes
wingman-mcp auth set --product access
wingman-mcp auth set --product identity_service
wingman-mcp auth set --product horizon_cloud
```

You will be prompted for the fields the product needs.

### Multiple environments

Each product can have multiple named environments (e.g. dev, staging, prod):

```bash
# Configure named environments per product
wingman-mcp auth set --product uem --env prod
wingman-mcp auth set --product horizon --env lab

# List configured environments; all products by default, or filter by product
wingman-mcp auth list
wingman-mcp auth list --product horizon

# Show status for one (product, env)
wingman-mcp auth status --product uem --env prod

# Test credentials (UEM also performs an OAuth token fetch)
wingman-mcp auth test --product horizon --env lab
```

When calling product API tools, pass the `env` parameter to target a specific environment. If omitted, the `default` environment is used.

UEM migration tools (`uem_migrate_*`) accept separate `source_env` and `dest_env` parameters to move resources between UEM environments.

### Remove credentials

```bash
wingman-mcp auth clear --product horizon
wingman-mcp auth clear --product uem --env prod
```

### Environment variable overrides

For CI, Docker, or headless environments where the OS keychain is unavailable, set credentials via environment variables; these take precedence over stored values.

The general namespace is `WINGMAN_MCP_<PRODUCT>_<FIELD>`:

```bash
# Horizon
export WINGMAN_MCP_HORIZON_USERNAME="admin"
export WINGMAN_MCP_HORIZON_PASSWORD="..."
export WINGMAN_MCP_HORIZON_SERVER_URL="https://horizon.example.com"
export WINGMAN_MCP_HORIZON_DOMAIN="CORP"

# App Volumes
export WINGMAN_MCP_APP_VOLUMES_USERNAME="admin"
export WINGMAN_MCP_APP_VOLUMES_PASSWORD="..."
export WINGMAN_MCP_APP_VOLUMES_MANAGER_URL="https://av.example.com"
```

For UEM, the original (unprefixed) env vars from before multi-product support continue to work as aliases:

```bash
export WINGMAN_MCP_CLIENT_ID="your-client-id"
export WINGMAN_MCP_CLIENT_SECRET="your-client-secret"
export WINGMAN_MCP_TOKEN_URL="https://na.uemauth.workspaceone.com/connect/token"
export WINGMAN_MCP_API_URL="https://as1831.awmdm.com"
```

(Equivalent to `WINGMAN_MCP_UEM_CLIENT_ID`, `WINGMAN_MCP_UEM_CLIENT_SECRET`, `WINGMAN_MCP_UEM_TOKEN_URL`, `WINGMAN_MCP_UEM_API_BASE_URL`.) Environment variables override credentials for all named environments and are best suited for single-environment setups.

## Export (backup)

Export all UEM resources from an organization group to disk:

```bash
wingman-mcp export
```

By default this uses the `default` environment, auto-detects the top-level OG, and saves to `~/.wingman-mcp/exports/`. A timestamped subdirectory is created for each export:

```
~/.wingman-mcp/exports/export_20260402_143000/
├── manifest.json        # Export metadata, counts, errors
├── scripts/             # Full script JSON (including base64 script_data)
├── sensors/             # Full sensor JSON (including base64 script_data)
├── profiles/            # Full profile JSON (V2 or metadata-transforms)
└── apps/                # App metadata JSON
    └── blobs/           # App binary files
```

Options:

```bash
# Export from a named environment
wingman-mcp export --env prod

# Export a specific OG by its group ID code (instead of auto-detecting the top-level one)
wingman-mcp export --group-id mychildog

# Custom output directory
wingman-mcp export -o ~/backups

# Export only specific resource types
wingman-mcp export --types scripts sensors

# Skip large app binary downloads
wingman-mcp export --no-blobs
```

## Upgrading

```bash
pip install --upgrade "wingman-mcp[rag]"
```

If a release ships updated RAG stores, replace them rather than merging in place:

```bash
cd ~/.wingman-mcp
mv stores stores.bak              # keep the old stores until you verify
mkdir stores
unzip -d stores stores_uem-<version>.zip
unzip -d stores stores_api-<version>.zip
unzip -d stores stores_release_notes-<version>.zip
```

Quit and relaunch your MCP clients so they pick up the new binary and stores. Then verify:

```bash
wingman-mcp status        # confirms stores load
wingman-mcp auth list     # confirms credentials carried over
```

Your `~/.wingman-mcp/config.json` and OS-keychain credentials persist across upgrades, so previously configured environments continue to work without re-entry.

## Installing with multiple Python versions

If you have multiple Python versions installed, a bare `pip install` may install against the wrong one. Use one of the approaches below to ensure you are using Python 3.10+.

### pyenv

```bash
pyenv versions
pyenv shell 3.12.4
pip install "wingman-mcp[rag]"
which wingman-mcp
# → /Users/you/.pyenv/versions/3.12.4/bin/wingman-mcp
```

### venv (recommended for isolation)

```bash
python3.12 -m venv ~/.venvs/wingman
source ~/.venvs/wingman/bin/activate
pip install "wingman-mcp[rag]"
which wingman-mcp
# → /Users/you/.venvs/wingman/bin/wingman-mcp
deactivate
```

> **Important:** When using a venv, you must use the full path to the binary in your MCP client configuration (e.g. `"/Users/you/.venvs/wingman/bin/wingman-mcp"`), since the venv will not be activated when the MCP client starts the server.

### conda

```bash
conda create -n wingman python=3.12 -y
conda activate wingman
pip install "wingman-mcp[rag]"
which wingman-mcp
# → /Users/you/miniconda3/envs/wingman/bin/wingman-mcp
```

> **Important:** As with venv, use the full binary path in your MCP client configuration since the conda environment will not be activated when the MCP client starts the server.

### Specifying Python explicitly (no version manager)

```bash
python3.12 -m pip install "wingman-mcp[rag]"
python3.12 -m pip show wingman-mcp | grep Location
```

## Troubleshooting

- **"RAG stores not found"**: Download and extract the store archives. See [Setup](#setup) step 3.
- **"... credentials are not configured"**: Run `wingman-mcp auth set --product <slug>` for whichever product the tool needs (e.g. `uem`, `horizon`, `app_volumes`, `access`, `identity_service`, `horizon_cloud`).
- **"HTTP 401" from a tool call**: Double-check the credentials for that product and environment with `wingman-mcp auth status --product <slug> --env <name>`. For UEM, `wingman-mcp auth test` also exercises the OAuth token fetch.
- **Server not detected**: Make sure `wingman-mcp` is on your PATH. Run `which wingman-mcp` to confirm. If it returns nothing, use `pip show wingman-mcp` to find the install location, then look for the binary in the `bin/` directory alongside it.
- **Wrong Python**: If you installed in a virtualenv or conda env, use the full path to the binary in your client config, e.g. `"/Users/you/.venvs/wingman/bin/wingman-mcp"`. See [Installing with multiple Python versions](#installing-with-multiple-python-versions).
- **`pip install` fails with a Python version error**: You are running pip from a Python version below 3.10. Use `python3.12 -m pip install ...` or activate the correct pyenv/conda/venv first.

## License

MIT
