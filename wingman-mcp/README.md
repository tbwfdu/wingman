# wingman-mcp

> Wingman — your AI sidekick for Workspace ONE UEM. Docs, APIs, and release notes, all one question away — right from your editor or AI chat app.

MCP server providing Workspace ONE UEM documentation search via local RAG and live API access to your UEM environment.

Exposes 33 tools over the [Model Context Protocol](https://modelcontextprotocol.io):

### Documentation search (local RAG — no auth required)

| Tool | Description |
|------|-------------|
| `search_uem_docs` | Product documentation (guides, enrollment, profiles, compliance, etc.) |
| `search_api_reference` | REST API endpoint reference (MDM, MAM, MCM, MEM, System) |
| `search_release_notes` | Release notes by version (what's new, bug fixes, resolved issues) |

### Live UEM API (requires auth — see [UEM API Authentication](#uem-api-authentication) below)

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

## What's included

```
wingman-mcp/
├── wingman_mcp-0.3.2-py3-none-any.whl   # Python package
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
pip install wingman_mcp-0.3.2-py3-none-any.whl
```

### 2. Place the stores

Copy the included `stores/` folder to a permanent location. The default location is `~/.wingman-mcp/stores/`:

```bash
mkdir -p ~/.wingman-mcp
cp -r stores ~/.wingman-mcp/stores
```

Or keep them wherever you like and set the environment variable:

```bash
export WINGMAN_MCP_DATA_DIR=/path/to/stores
```

### 3. Verify

```bash
wingman-mcp status
```

You should see all three stores listed with their sizes.

## Client configuration

The server uses **stdio** transport, which is supported by all MCP-compatible clients. The command to start the server is always:

```
wingman-mcp serve
```

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
```

### Environment variable overrides

For CI, Docker, or headless environments where the OS keychain is unavailable, you can set credentials via environment variables. These take precedence over stored values:

```bash
export WINGMAN_MCP_CLIENT_ID="your-client-id"
export WINGMAN_MCP_CLIENT_SECRET="your-client-secret"
export WINGMAN_MCP_TOKEN_URL="https://na.uemauth.workspaceone.com/connect/token"
export WINGMAN_MCP_API_URL="https://as1831.awmdm.com"
```

## Troubleshooting

- **"RAG stores not found"** — Copy the stores folder. See Setup Step 2.
- **"UEM API credentials are not configured"** — Run `wingman-mcp auth set` to provide your OAuth credentials.
- **"HTTP 401" from auth test** — Double-check your Client ID, Client Secret, and Token URL.
- **Server not detected** — Make sure `wingman-mcp` is on your PATH. Run `which wingman-mcp` to confirm.
- **Wrong Python** — If you installed in a virtualenv, use the full path to the binary in your client config, e.g. `"/Users/you/.venvs/wingman/bin/wingman-mcp"`.
