# Wingman

> Your AI sidekick for Omnissa EUC.

Wingman gives AI assistants deep knowledge of Omnissa EUC products — documentation, REST API reference, release notes, and live access to your environments. Ask questions in natural language and get answers grounded in real docs and real data from your tenant.

## Two ways to run it

| | **wingman-mcp** | **Wingman container** |
|---|---|---|
| Best for | An individual on their own machine | A team or org running a shared server |
| Install | `pip install "wingman-mcp[rag]"` | `docker run ghcr.io/tbwfdu/wingman-mcp-server` |
| Transport | Local (stdio) | HTTP (Streamable-HTTP) |
| Credentials | Your own, via `wingman-mcp auth set` | Per-user headers, or shared admin environments |
| Access control | n/a (single user) | Full / read-only / admin access keys |

Both expose the same tools — offline documentation search plus live API tools across UEM, Horizon, App Volumes, Access, Identity Service, and Horizon Cloud.

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

## Wingman container (self-hosted server)

A single container that serves Wingman over HTTP, so a whole team can share one
deployment instead of each person installing the package. No Azure, no Entra, no
API keys — you bring one or more access keys and run the image. On first boot the
documentation, REST API reference, and release-notes RAG stores (~1.6 GB) are
downloaded from a public GitHub Release into `/data/stores`; mount a volume there
and the download happens only once.

- **Multi-user** — hand out full, read-only, and admin access keys, presented in
  the `X-Wingman-Access-Key` header. Read-only callers are blocked from any tool
  that changes an environment or bulk-exports data.
- **Per-user credentials** — each user supplies their own product credentials as
  request headers, scoped to the request and never stored.
- **Shared environments (admin API)** — or an admin configures product
  environments once (encrypted at rest) and every user shares them.

### First run

```bash
docker run -d --name wingman \
  -p 8000:8000 \
  -e WINGMAN_MCP_ACCESS_KEY=$(openssl rand -hex 32) \
  -v wingman-stores:/data/stores \
  ghcr.io/tbwfdu/wingman-mcp-server:latest

# Watch the one-time store download on first boot
docker logs -f wingman

# Once it's up:
curl localhost:8000/health   # -> ok
```

The `-v wingman-stores:/data/stores` named volume caches the RAG stores so later
starts are instant. The server listens on `:8000` and refuses to start unless at
least one access key is configured. To set several variables at once, put them in
a file and pass `--env-file`:

```bash
cat > wingman.env <<'EOF'
WINGMAN_MCP_ACCESS_KEY=<full-access-key>
WINGMAN_MCP_READONLY_ACCESS_KEY=<read-only-key>
EOF

docker run -d --name wingman -p 8000:8000 \
  --env-file wingman.env -v wingman-stores:/data/stores \
  ghcr.io/tbwfdu/wingman-mcp-server:latest
```

### Environment variables

| Env var | Required | Purpose |
|---|---|---|
| `WINGMAN_MCP_ACCESS_KEY` | Yes\* | Full-access key, presented via the `X-Wingman-Access-Key` header. |
| `WINGMAN_MCP_READONLY_ACCESS_KEY` | No | Read-only key (same header); can call only non-mutating tools. |
| `WINGMAN_MCP_ADMIN_KEY` | No | Enables the `/admin` API for shared environments. |
| `WINGMAN_MCP_ENCRYPTION_KEY` | If admin key set | Encrypts the admin store at rest. The admin API won't start without it. |
| `WINGMAN_MCP_ADMIN_STORE_PATH` | No | Path to the encrypted admin store. Default `~/.wingman-mcp/admin/environments.enc`; point at a mounted volume to persist. |
| `WINGMAN_MCP_ALLOW_ENV_SELECTION` | No | When set (`1`/`true`), lets a tool call target any admin environment via its `env` argument. Off by default. Needs the admin key. |
| `WINGMAN_MCP_EXTRA_MUTATING_TOOLS` | No | Comma-separated tool names to additionally treat as mutating (forward-compat for tools added after this image was built). |
| `WINGMAN_MCP_PUBLIC_URL` | No | Canonical URL advertised in discovery docs when behind a proxy / custom domain. |
| `WINGMAN_MCP_DATA_DIR` | No | Where the RAG stores live. Defaults to `/data/stores` in the image; mount a volume here to cache them across restarts. |

\* At least one of `WINGMAN_MCP_ACCESS_KEY` or `WINGMAN_MCP_READONLY_ACCESS_KEY`
must be set, or the server refuses to start.

### Access tiers

Hand out different keys for different levels of access — all optional and
independent, so set only the ones you need. A caller presents exactly one key.

| Tier | Env var | Header | Can do |
|---|---|---|---|
| **Full** | `WINGMAN_MCP_ACCESS_KEY` | `X-Wingman-Access-Key` | Any tool, including ones that change the environment. |
| **Read-only** | `WINGMAN_MCP_READONLY_ACCESS_KEY` | `X-Wingman-Access-Key` | Non-mutating tools only. |
| **Admin** | `WINGMAN_MCP_ADMIN_KEY` | `X-Wingman-Admin-Key` | Manage shared environments via the `/admin` API. |

Full and read-only share the `X-Wingman-Access-Key` header — the server tells
them apart by value.

### Connect an MCP client

Point any Streamable-HTTP MCP client at the server and send your key in the
`X-Wingman-Access-Key` header:

```json
{
  "mcpServers": {
    "wingman": {
      "type": "http",
      "url": "http://localhost:8000",
      "headers": { "X-Wingman-Access-Key": "<your-access-key>" }
    }
  }
}
```

The documentation-search tools work immediately; the live API tools activate once
credentials are available — either per-user via `X-*` headers, or from a shared
admin environment. To configure shared environments, set `WINGMAN_MCP_ADMIN_KEY`
and `WINGMAN_MCP_ENCRYPTION_KEY` and manage them over the `/admin` API.

### Updating

```bash
docker pull ghcr.io/tbwfdu/wingman-mcp-server:latest
docker rm -f wingman && docker run -d --name wingman -p 8000:8000 \
  --env-file wingman.env -v wingman-stores:/data/stores \
  ghcr.io/tbwfdu/wingman-mcp-server:latest
```

## License

See [LICENSE](LICENSE) for details.
