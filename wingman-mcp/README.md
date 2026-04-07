# wingman-mcp

> Wingman — your AI sidekick for Workspace ONE UEM. Docs, APIs, and release notes, all one question away — right from your editor or AI chat app.

MCP server providing Workspace ONE UEM documentation search via local RAG and live API access to your UEM environment.

Exposes 40 tools over the [Model Context Protocol](https://modelcontextprotocol.io):

### Documentation search (local RAG — no auth required)

| Tool | Description |
|------|-------------|
| `search_uem_docs` | Product documentation (guides, enrollment, profiles, compliance, etc.) |
| `search_api_reference` | REST API endpoint reference (MDM, MAM, MCM, MEM, System) |
| `search_release_notes` | Release notes by version (what's new, bug fixes, resolved issues) |

### Live UEM API (requires auth — see [UEM API Authentication](#uem-api-authentication) below)

#### Environments

| Tool | Description |
|------|-------------|
| `uem_list_environments` | List all configured UEM environments and their connection status |

#### Devices

| Tool | Description |
|------|-------------|
| `uem_search_devices` | Search/filter managed devices by user, platform, model, compliance, ownership |
| `uem_get_device` | Get full device details by device ID |
| `uem_get_device_profiles` | List profiles installed on a device |
| `uem_get_device_apps` | List apps installed on a device |
| `uem_get_device_security` | Device security info (encryption, passcode, compromised status) |
| `uem_get_device_network` | Device network info (IPs, MAC, WiFi, cellular) |
| `uem_send_device_command` | Send commands to a device (DeviceQuery, Lock, EnterpriseWipe, etc.) |

#### Users & Organization Groups

| Tool | Description |
|------|-------------|
| `uem_search_users` | Search enrollment users by name, email, username |
| `uem_get_user` | Get enrollment user details by user ID |
| `uem_search_organization_groups` | Search organization groups (OGs) |
| `uem_get_organization_group` | Get OG details by ID |
| `uem_get_og_children` | List child OGs under a parent |
| `uem_search_smart_groups` | Search smart groups |

#### Profiles

| Tool | Description |
|------|-------------|
| `uem_search_profiles` | Search device profiles by name, platform, status |
| `uem_get_profile` | Get full profile details by ID (V2 round-trip or metadata-transforms fallback) |
| `uem_create_profile` | Create a profile from V2 JSON (Windows all payloads; Apple/Android V2 payloads) |

#### Scripts

| Tool | Description |
|------|-------------|
| `uem_search_scripts` | List all scripts for an organization group |
| `uem_get_script` | Get full script details by UUID (including base64 script data) |
| `uem_create_script` | Create a script from individual parameters (name, platform, script content) |
| `uem_create_script_from_json` | Create a script from JSON (round-trip from `uem_get_script`) |

#### Sensors

| Tool | Description |
|------|-------------|
| `uem_search_sensors` | List all sensors for an organization group |
| `uem_get_sensor` | Get full sensor details by UUID (including base64 script data) |
| `uem_create_sensor` | Create a sensor from individual parameters (name, platform, script content) |
| `uem_create_sensor_from_json` | Create a sensor from JSON (round-trip from `uem_get_sensor`) |

#### Applications

| Tool | Description |
|------|-------------|
| `uem_search_apps` | Search applications by name, bundle ID, platform |
| `uem_get_app` | Get full app details by ID (includes blob GUID and original filename) |
| `uem_download_app_blob` | Download an application binary to disk |

#### Compliance & Security Baselines

| Tool | Description |
|------|-------------|
| `uem_search_compliance_policies` | Search compliance policies by organization group |
| `uem_get_baseline_templates` | List security baseline vendor templates (Microsoft, CIS) and OS versions |
| `uem_search_baseline_policies` | Browse GPO policies in a baseline catalog version |
| `uem_get_baseline_policy` | Get full details of a baseline policy by UUID |

#### Export (backup)

| Tool | Description |
|------|-------------|
| `uem_export_all` | Export all resources (scripts, sensors, profiles, apps) from an OG to disk |

Exports create a timestamped directory with a `manifest.json` and individual JSON files for each resource. App binaries are optionally downloaded alongside metadata. All fields (including read-only ones) are preserved. Exported resources can be re-imported using the `create_*_from_json` tools.

#### Migration (cross-environment)

| Tool | Description |
|------|-------------|
| `uem_migrate_scripts` | Migrate all scripts from one UEM environment/OG to another |
| `uem_migrate_sensors` | Migrate all sensors from one UEM environment/OG to another |
| `uem_migrate_profiles` | Migrate V2-compatible profiles between environments (with optional platform filter) |
| `uem_migrate_apps` | Migrate internal applications (including binaries) between environments |

Migration tools require two named environments to be configured (source and destination). They skip resources that already exist in the destination by name. Smart group assignments are stripped from profiles since IDs differ between environments.

## What's included

```
wingman-mcp/
├── wingman_mcp-0.4.0-py3-none-any.whl   # Python package
├── stores/                                # Pre-built RAG databases
│   ├── uem/                               #   UEM product documentation
│   ├── api/                               #   REST API reference
│   └── release_notes/                     #   Release notes
└── README.md
```

## Prerequisites

- Python 3.10+

## Setup

### 1. Install the package

```bash
pip install wingman_mcp-0.4.0-py3-none-any.whl
```

> **Multiple Python versions?** If you have more than one Python version installed (via pyenv, Homebrew, system Python, etc.), make sure you install with Python 3.10+. See [Installing with multiple Python versions](#installing-with-multiple-python-versions) below.

### 2. Find the binary path

After installing, find the full path to the `wingman-mcp` binary — you'll need this for client configuration:

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

> **Tip:** If `which wingman-mcp` returns nothing, the install location isn't on your PATH. Use `find` or `pip show` to locate it — see [Troubleshooting](#troubleshooting).

Use the full path as the `command` in your MCP client configuration to avoid PATH issues. For example, instead of `"command": "wingman-mcp"`, use `"command": "/Users/you/.pyenv/versions/3.12.4/bin/wingman-mcp"`.

### 3. Place the stores

Copy the included `stores/` folder to a permanent location. The default location is `~/.wingman-mcp/stores/`:

```bash
mkdir -p ~/.wingman-mcp
cp -r stores ~/.wingman-mcp/stores
```

Or keep them wherever you like and set the environment variable:

```bash
export WINGMAN_MCP_DATA_DIR=/path/to/stores
```

### 4. Verify

```bash
wingman-mcp status
```

You should see all three stores listed with their sizes.

## Client configuration

The server uses **stdio** transport, which is supported by all MCP-compatible clients. The command to start the server is:

```
wingman-mcp serve
```

> **Full path recommended:** MCP clients launch the server as a subprocess without your shell profile, so pyenv/conda/venv may not be active. Use the full binary path from `which wingman-mcp` (e.g. `"/Users/you/.venvs/wingman/bin/wingman-mcp"`) to avoid "command not found" errors.

If you placed the stores in the default location (`~/.wingman-mcp/stores/`), no `env` block is needed. If you placed them elsewhere, add the `WINGMAN_MCP_DATA_DIR` env variable as shown below.

### Codex

You can add the server to Codex with the CLI:

```bash
codex mcp add wingman -- wingman-mcp serve
```

If your stores are not in the default location, include the environment variable when adding it:

```bash
codex mcp add wingman --env WINGMAN_MCP_DATA_DIR=/path/to/stores -- wingman-mcp serve
```

Verify the server is configured:

```bash
codex mcp list
```

You can also add it directly to `~/.codex/config.toml`:

```toml
[mcp_servers.wingman]
command = "wingman-mcp"
args = ["serve"]

[mcp_servers.wingman.env]
WINGMAN_MCP_DATA_DIR = "/path/to/stores"
```

If you are using the default store location (`~/.wingman-mcp/stores/`), you can omit the `[mcp_servers.wingman.env]` block.

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

Add to `.claude/settings.json` or `~/.claude/settings.json`:

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

## Export (backup)

Export all UEM resources from an organization group to disk:

```bash
wingman-mcp export
```

That's it. By default this uses the `default` environment, auto-detects the top-level OG, and saves to `~/.wingman-mcp/exports/`. A timestamped subdirectory is created for each export:

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

## UEM API Authentication

The live API tools connect to your Workspace ONE UEM environment using OAuth 2.0 (client credentials). This is optional — the RAG documentation search tools work without it.

### What you need

- **UEM API Base URL** — Your UEM console URL (e.g. `https://as1831.awmdm.com`)
- **OAuth Token URL** — Your region's token endpoint (e.g. `https://na.uemauth.workspaceone.com/connect/token`)
- **Client ID** — OAuth client ID from your UEM console
- **Client Secret** — OAuth client secret

### Configure credentials

```bash
wingman-mcp auth set
```

This prompts for each value interactively. Secrets (Client ID and Client Secret) are stored in your OS keychain (macOS Keychain, Windows Credential Manager, or Linux Secret Service). The Token URL and API Base URL are stored in `~/.wingman-mcp/config.json`.

### Multiple environments

You can configure multiple UEM environments (e.g. dev, staging, prod) using the `--env` flag:

```bash
# Configure a named environment
wingman-mcp auth set --env prod
wingman-mcp auth set --env dev

# List all configured environments
wingman-mcp auth list

# Test a specific environment
wingman-mcp auth test --env prod

# Show status for a specific environment
wingman-mcp auth status --env prod
```

When calling UEM API tools, pass the `env` parameter to target a specific environment. If omitted, the `default` environment is used.

Migration tools (`uem_migrate_*`) accept separate `source_env` and `dest_env` parameters to move resources between environments.

### Verify configuration

```bash
# Show what's configured (secrets are masked)
wingman-mcp auth status

# Test the OAuth token fetch against your token URL
wingman-mcp auth test
```

### Remove credentials

```bash
wingman-mcp auth clear

# Clear a specific environment
wingman-mcp auth clear --env prod
```

### Environment variable overrides

For CI, Docker, or headless environments where the OS keychain is unavailable, you can set credentials via environment variables. These take precedence over stored values:

```bash
export WINGMAN_MCP_CLIENT_ID="your-client-id"
export WINGMAN_MCP_CLIENT_SECRET="your-client-secret"
export WINGMAN_MCP_TOKEN_URL="https://na.uemauth.workspaceone.com/connect/token"
export WINGMAN_MCP_API_URL="https://as1831.awmdm.com"
```

Note: environment variables override credentials for all named environments. They are best suited for single-environment setups (CI/Docker).

## Installing with multiple Python versions

If you have multiple Python versions installed, a bare `pip install` may install against the wrong one. Use one of the approaches below to ensure you're using Python 3.10+.

### pyenv

```bash
# Check available versions
pyenv versions

# Set your shell to a 3.10+ version (if not already)
pyenv shell 3.12.4

# Install
pip install wingman_mcp-0.4.0-py3-none-any.whl

# Confirm the binary location
which wingman-mcp
# → /Users/you/.pyenv/versions/3.12.4/bin/wingman-mcp
```

### venv (recommended for isolation)

```bash
# Create a virtual environment with Python 3.10+
python3.12 -m venv ~/.venvs/wingman

# Activate it
source ~/.venvs/wingman/bin/activate

# Install
pip install wingman_mcp-0.4.0-py3-none-any.whl

# Confirm the binary location
which wingman-mcp
# → /Users/you/.venvs/wingman/bin/wingman-mcp

# You can deactivate now — the binary stays at the path above
deactivate
```

> **Important:** When using a venv, you must use the full path to the binary in your MCP client configuration (e.g. `"/Users/you/.venvs/wingman/bin/wingman-mcp"`), since the venv won't be activated when the MCP client starts the server.

### conda

```bash
# Create an environment with Python 3.10+
conda create -n wingman python=3.12 -y

# Activate it
conda activate wingman

# Install
pip install wingman_mcp-0.4.0-py3-none-any.whl

# Confirm the binary location
which wingman-mcp
# → /Users/you/miniconda3/envs/wingman/bin/wingman-mcp
```

> **Important:** As with venv, use the full binary path in your MCP client configuration since the conda environment won't be activated when the MCP client starts the server.

### Specifying Python explicitly (no version manager)

If you have multiple Python versions but don't use pyenv/conda, target the right one directly:

```bash
# Use a specific Python version's pip
python3.12 -m pip install wingman_mcp-0.4.0-py3-none-any.whl

# Find where it installed
python3.12 -m pip show wingman-mcp | grep Location
```

## Troubleshooting

- **"RAG stores not found"** — Copy the stores folder. See Setup Step 2.
- **"UEM API credentials are not configured"** — Run `wingman-mcp auth set` to provide your OAuth credentials.
- **"HTTP 401" from auth test** — Double-check your Client ID, Client Secret, and Token URL.
- **Server not detected** — Make sure `wingman-mcp` is on your PATH. Run `which wingman-mcp` to confirm. If it returns nothing, the binary isn't on your PATH — use `pip show wingman-mcp` to find the install location, then look for the binary in the `bin/` directory alongside that location.
- **Wrong Python** — If you installed in a virtualenv or conda env, use the full path to the binary in your client config, e.g. `"/Users/you/.venvs/wingman/bin/wingman-mcp"`. See [Installing with multiple Python versions](#installing-with-multiple-python-versions).
- **`pip install` fails with Python version error** — You're running pip from a Python version below 3.10. Use `python3.12 -m pip install ...` or activate the correct pyenv/conda/venv first.
