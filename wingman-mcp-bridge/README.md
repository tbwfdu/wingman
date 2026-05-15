# wingman-mcp-bridge

A local stdio bridge to a remote, Entra-protected wingman-mcp server.

This package is **private**. It is distributed only to users who have been
approved to use the hosted wingman-mcp server.

## What it does

The bridge runs as a local stdio MCP server and forwards every request to
the remote HTTP server. It exists so a Claude config can stay a clean
`command` + `args` one-liner while credentials stay in the OS keychain:

- The Entra bearer token is obtained once via a browser sign-in and cached
  in the OS keychain, then refreshed transparently.
- Per-tenant API credentials (UEM, Horizon, etc.) are read from the OS
  keychain on every request and forwarded as `X-*` headers over TLS.

Nothing sensitive is written to `claude_desktop_config.json` or
`~/.claude.json`.

## Install

The bridge depends on the public `wingman-mcp` package for the credential
schema. For local development, install that editable first:

```bash
pip install -e ../wingman-mcp
pip install -e .
```

For release installs, the dependency resolves from the pinned git tag in
`pyproject.toml`.

## Usage

```bash
# 1. Store per-tenant credentials in the OS keychain (once per product)
wingman-mcp auth set --product uem

# 2. Sign in to the remote server (opens a browser; token cached in keychain)
wingman-mcp-bridge login

# 3. Write the bridge entry into Claude Desktop / Claude Code config
wingman-mcp-bridge link

# Inspect the result first without writing files:
wingman-mcp-bridge link --dry-run
```

`link` writes an mcpServers entry that runs `wingman-mcp-bridge serve`. The
bridge process is what Claude launches; you do not run `serve` by hand.

Other commands:

```bash
wingman-mcp-bridge logout              # clear the cached token
wingman-mcp-bridge serve --remote URL  # run the bridge (Claude does this)
```

All commands default to `https://wingman.omnissafoundry.com/mcp`; pass
`--remote URL` to target a different server.

## Prerequisite: Entra redirect URI

The browser sign-in uses a loopback redirect. The Wingman MCP Client app
registration in Entra must list `http://localhost/callback` under
Authentication, Mobile and desktop applications. Entra wildcards the port
for `localhost` redirect URIs, so the bridge's random port matches; the
`/callback` path must be registered exactly. Without it, `login` returns
`AADSTS50011` (redirect URI mismatch).
