# wingman-mcp-server

The HTTP transport, Entra ID authentication, OAuth shim, and RAG ingestion
for wingman-mcp.

This package is **private** and maintainer-only. It depends on the public
`wingman-mcp` package for the shared MCP tool layer and RAG search; it adds
the Streamable HTTP transport, request authentication, and the commands
that build the vector stores.

## Install

For local development, install the public package editable (with the RAG
extra) first, then this package:

```bash
pip install -e "../wingman-mcp[rag]"
pip install -e .
```

For release installs the `wingman-mcp[rag]` dependency resolves from the
pinned git tag in `pyproject.toml`.

## Commands

```bash
wingman-mcp-server serve              # run the HTTP server
wingman-mcp-server ingest             # build the RAG vector stores
wingman-mcp-server ingest --list      # list ingestable stores
wingman-mcp-server check              # report what a rebuild would change
```

## Running the HTTP server

`serve` runs the MCP server over Streamable HTTP. Each request must present
either a valid Entra ID access token or the static fallback key; the server
refuses to start if neither path is configured.

Environment variables read at startup:

| Var | Required | Default | Purpose |
|---|---|---|---|
| `ENTRA_TENANT_ID` | If using JWT auth | (none) | Single Entra tenant accepted by the server. |
| `ENTRA_APP_ID_URI` | No | `api://wingman-mcp` | App ID URI used to qualify OAuth scopes. |
| `ENTRA_AUDIENCE` | No | value of `ENTRA_APP_ID_URI` | Expected `aud` claim of incoming tokens. |
| `ENTRA_REQUIRED_SCOPE` | No | `mcp.access` | Required scope in the `scp` claim. Set empty to skip. |
| `WINGMAN_MCP_ACCESS_KEY` | If JWT auth is not used | (none) | Enables the static-key fallback via the `X-Wingman-Access-Key` header. |
| `WINGMAN_MCP_PUBLIC_URL` | No | (derived from `Host`) | Canonical URL advertised in OAuth discovery, e.g. `https://wingman.example.com`. |
| `ENTRA_CLIENT_ID` | No | (none) | Pre-registered Entra client app ID. With `ENTRA_TENANT_ID`, enables the OAuth DCR shim. |

When `ENTRA_TENANT_ID` is set, the server publishes RFC 9728 protected
resource metadata at `/.well-known/oauth-protected-resource`. When
`ENTRA_CLIENT_ID` is also set, the OAuth shim makes Entra look RFC
7591-compatible to MCP clients: it advertises the server itself as the
authorization server and proxies `/oauth/{register,authorize,token}` to
Entra v2.

Per-user product credentials travel in `X-*` request headers and are never
stored server-side.

## Deployment

Azure Container Apps deployment lives in `http-deployment/`:

- `main.bicep` / `params.bicepparam`: infrastructure as code
- `deploy.sh`: build and deploy script
- `http-deployment/README.md`: deployment walkthrough

## Ingestion

`ingest` and `check` build and audit the local Chroma vector stores. See
`INGEST_MACOS.md` for the full incremental-refresh workflow, including
release-notes capture and syncing stores to Azure Files.
