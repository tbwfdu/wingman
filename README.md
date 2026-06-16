# Wingman

> Your AI sidekick for Omnissa EUC.

Wingman gives AI assistants deep knowledge of Omnissa EUC products — documentation, REST API reference, release notes, and live access to your environments. Ask questions in natural language and get answers grounded in real docs and real data from your tenant.

## wingman-mcp

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

## License

See [LICENSE](LICENSE) for details.
