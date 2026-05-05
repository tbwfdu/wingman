# Wingman

> Your AI sidekick for Workspace ONE UEM.

Wingman gives AI assistants deep knowledge of Workspace ONE UEM — product documentation, REST API reference, release notes, and live access to your UEM environment. Ask questions in natural language and get answers grounded in real docs and real data from your tenant.

## Components

| Component | Description | Status |
|-----------|-------------|--------|
| [wingman-mcp](wingman-mcp/) | MCP server — documentation search (local RAG) and live UEM API tools | :green_circle: Available |

## wingman-mcp

An [MCP server](https://modelcontextprotocol.io) that runs locally and exposes 40 tools to any MCP-compatible AI client (Claude Code, Claude Desktop, Cursor, VS Code Copilot, Windsurf, Codex, and more).

**Documentation search** — instant, offline search across UEM product docs, REST API reference, and release notes using local RAG. No API keys or network access required.

**Live UEM API** — search devices, users, profiles, apps, smart groups, and organization groups in your own UEM environment. Send device commands. Authenticate once with `wingman-mcp auth set` and your AI assistant can query your tenant directly.

See [wingman-mcp/README.md](wingman-mcp/README.md) for setup instructions and the full tool list.

### Quick start

```bash
# Install
pip install wingman-mcp/wingman_mcp-(version)-py3-none-any.whl

# Place the pre-built RAG stores
mkdir -p ~/.wingman-mcp
cp -r wingman-mcp/stores ~/.wingman-mcp/stores

# Verify
wingman-mcp status

# (Optional) Connect to your UEM environment for live API tools
wingman-mcp auth set
wingman-mcp auth test
```

Then add `wingman-mcp serve` to your MCP client of choice. See [wingman-mcp/README.md](wingman-mcp/README.md) for client-specific configuration (Claude, Cursor, VS Code, etc.).

## License

See [LICENSE](LICENSE) for details.
