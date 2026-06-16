# Wingman

> Your AI sidekick for Omnissa EUC.

Wingman gives AI assistants deep knowledge of Omnissa EUC products — documentation, REST API reference, release notes, and live access to your environments. Ask questions in natural language and get answers grounded in real docs and real data from your tenant.

The repo is split into three packages: one public package for local use, and two private packages that together make up the hosted server deployment.

## Components

| Component | Visibility | Description |
|-----------|------------|-------------|
| [wingman-mcp](wingman-mcp/) | Public | MCP server — local RAG documentation search and live API tools. Runs on the user's machine over stdio. |
| [wingman-mcp-server](wingman-mcp-server/) | Private | HTTP transport, Entra ID authentication, OAuth shim, and RAG ingestion for the hosted deployment. |
| [wingman-mcp-bridge](wingman-mcp-bridge/) | Private | Local stdio bridge that forwards MCP requests to the remote `wingman-mcp-server` with Entra token auth and per-tenant credential forwarding. |

## wingman-mcp (public)

An [MCP server](https://modelcontextprotocol.io) that runs locally and exposes tools to any MCP-compatible AI client (Claude Code, Claude Desktop, Cursor, VS Code Copilot, Windsurf, Codex, and more).

**Documentation search** — instant, offline search across product docs, REST API reference, and release notes using local RAG. No API keys or network access required.

**Live API tools** — search devices, users, profiles, apps, smart groups, and organization groups across UEM, Horizon, App Volumes, Access, Identity Service, and Horizon Cloud. Authenticate once with `wingman-mcp auth set` and your AI assistant can query your tenant directly.

See [wingman-mcp/README.md](wingman-mcp/README.md) for setup instructions and the full tool list.

### Quick start

```bash
pip install "wingman-mcp[rag]"
wingman-mcp status
wingman-mcp auth set   # optional: connect to your environment for live API tools
```

Then add `wingman-mcp serve` to your MCP client of choice. See [wingman-mcp/README.md](wingman-mcp/README.md) for client-specific configuration.

## wingman-mcp-server (private)

The server-side package for the hosted deployment. Wraps the `wingman-mcp` tool layer in a Streamable HTTP transport, adds Entra ID JWT validation (with an RFC 7591-compatible OAuth shim), and provides the `ingest` and `check` commands for building and auditing the vector stores.

See [wingman-mcp-server/README.md](wingman-mcp-server/README.md) for deployment and ingestion details.

## wingman-mcp-bridge (private)

A local stdio bridge distributed to approved users of the hosted server. It runs as a local MCP process (so Claude config stays a simple `command` + `args` entry), obtains and caches an Entra bearer token via browser sign-in, and forwards requests over TLS with per-tenant credentials read from the OS keychain.

See [wingman-mcp-bridge/README.md](wingman-mcp-bridge/README.md) for setup.

## License

See [LICENSE](LICENSE) for details.
