# Third-Party Client — RAG-Only Access Flow

How a third-party MCP client (for example, a JIRA integration) interacts with
the wingman-mcp server to use **only** the RAG documentation search tools, and
not the UEM / Horizon environment tools.

## The short version

The RAG search tools query a **local, read-only documentation index** and need
no product credentials. The environment tools call live UEM / Horizon APIs and
require per-request credentials. A third-party client is confined to RAG by
**what it does not send**: it authenticates to the transport, then simply omits
the product credential headers. Without those headers the environment tools
cannot run, while the RAG tools work normally.

> [!IMPORTANT]
> "RAG-only" is **not enforced by a scope or an allowlist.** The server lists
> every tool to every client (`list_tools()` returns a static list). The
> restriction is *implicit*: environment tools call `_require_auth()` /
> `_get_product_client()` and raise a `ToolError` when no credentials are
> present. If you need a hard, server-enforced guarantee, that does not exist
> today and would require a separate change. See [Limits](#limits-of-this-model).

```mermaid
flowchart TD
    Client["Third-party MCP client<br/><span>e.g. JIRA integration</span><br/><br/>Authorization: Bearer &lt;jwt&gt;<br/>or X-Wingman-Access-Key<br/><b>NO product X-* credential headers</b>"]

    Uvicorn["Uvicorn ASGI server<br/><span>/mcp endpoint</span>"]

    subgraph Stack["ASGI middleware stack"]
        direction TB
        Entra{"EntraAuthMiddleware<br/><span>validate identity — REQUIRED</span>"}
        Cred["CredentialHeaderMiddleware<br/><span>no X-* product headers found</span><br/><span>_request_credentials = None</span>"]
        Router["_App router<br/><span>route → /mcp</span>"]
    end

    Reject["401 / 403<br/><span>no valid identity</span>"]

    Session["StreamableHTTPSessionManager<br/><span>stateless dispatch</span>"]
    Dispatch{"call_tool<br/><span>which tool?</span>"}

    subgraph RAGPath["RAG path — available"]
        direction TB
        RAG["RAG search tools<br/><span>search_uem_docs · search_api_reference</span><br/><span>search_release_notes · search_omnissa_docs</span><br/><span>no _require_auth — credentials never checked</span>"]
        Stores[("Local Chroma vector stores<br/><span>~/.wingman-mcp/stores/&lt;product&gt;/chroma.sqlite3</span><br/><span>embeddings: all-MiniLM-L6-v2 · read-only</span>")]
    end

    subgraph EnvPath["Environment path — blocked for this client"]
        direction TB
        Env["Environment tools<br/><span>uem_* · horizon_* · app_volumes_* · access_* · …</span><br/><span>call _require_auth() / _get_product_client()</span>"]
        Blocked["ToolError — no credentials configured<br/><span>effectively unreachable without X-* headers</span>"]
    end

    Client -->|"POST /mcp · JSON-RPC"| Uvicorn
    Uvicorn --> Entra
    Entra -->|"invalid / missing"| Reject
    Entra -->|"valid"| Cred
    Cred --> Router
    Router --> Session
    Session --> Dispatch

    Dispatch -->|"search_* (RAG)"| RAG
    RAG -->|"vector similarity search"| Stores
    Stores -. "JSON results" .-> Client

    Dispatch -->|"uem_* / horizon_* / … (environment)"| Env
    Env --> Blocked

    classDef client fill:#1e293b,stroke:#0f172a,color:#f8fafc
    classDef server fill:#334155,stroke:#1e293b,color:#f8fafc
    classDef gate fill:#1e293b,stroke:#475569,color:#e2e8f0
    classDef cred fill:#7c3aed,stroke:#5b21b6,color:#f5f3ff
    classDef rag fill:#15803d,stroke:#166534,color:#f0fdf4
    classDef store fill:#0e7490,stroke:#155e75,color:#ecfeff
    classDef blocked fill:#6b7280,stroke:#374151,color:#f9fafb,stroke-dasharray:5 4
    classDef reject fill:#dc2626,stroke:#991b1b,color:#fef2f2

    class Client client
    class Uvicorn,Session server
    class Entra,Dispatch,Router gate
    class Cred cred
    class RAG rag
    class Stores store
    class Env,Blocked blocked
    class Reject reject
```

## API endpoints and request types

All MCP traffic for the RAG-only flow goes to a **single HTTP endpoint, `/mcp`,
by HTTP `POST`** — the transport is MCP Streamable HTTP. The JSON-RPC "method"
inside each POST body is what changes between calls. The OAuth `/.well-known`
and `/oauth/*` endpoints are only touched once, at first connect, and only when
the client uses Entra ID rather than a static access key.

### HTTP endpoints

| Method | Endpoint | Used for | When |
|--------|----------|----------|------|
| `POST` | `/mcp` | All MCP JSON-RPC messages (`initialize`, `tools/list`, `tools/call`) | Every request |
| `GET` | `/mcp` | Optional server→client SSE stream | Rarely — not needed in stateless mode |
| `DELETE` | `/mcp` | Session termination | Returns `405` in stateless mode (no session) |
| `GET` | `/health` | Liveness probe | Optional; unauthenticated |
| `GET` | `/.well-known/oauth-protected-resource` | RFC 9728 resource discovery | First connect, Entra auth only |
| `GET` | `/.well-known/oauth-authorization-server` | RFC 8414 AS discovery | First connect, Entra auth only |
| `POST` | `/oauth/register` | RFC 7591 client registration shim | First connect, Entra auth only |
| `GET` | `/oauth/authorize` | `302` redirect to Entra sign-in | First connect, Entra auth only |
| `POST` | `/oauth/token` | Token exchange proxied to Entra | First connect + token refresh, Entra auth only |

### MCP JSON-RPC request types (inside `POST /mcp`)

| JSON-RPC method | Kind | Purpose |
|-----------------|------|---------|
| `initialize` | request | Protocol + capability handshake |
| `notifications/initialized` | notification | Client signals it is ready |
| `tools/list` | request | Retrieve the tool catalogue |
| `tools/call` | request | Invoke a tool — here, a `search_*` RAG tool |

### Request sequence

```mermaid
sequenceDiagram
    autonumber
    participant C as JIRA MCP client
    participant S as wingman-mcp server
    participant V as Chroma vector stores

    opt First connect — only when using Entra ID (skipped for static-key auth)
        C->>S: GET /.well-known/oauth-protected-resource
        S-->>C: 200 · RFC 9728 metadata
        C->>S: GET /.well-known/oauth-authorization-server
        S-->>C: 200 · RFC 8414 metadata
        C->>S: POST /oauth/register
        S-->>C: 201 · client_id
        C->>S: GET /oauth/authorize
        S-->>C: 302 · redirect to Entra sign-in
        C->>S: POST /oauth/token
        S-->>C: 200 · access token
    end

    Note over C,S: MCP session — every message is POST /mcp. Each request carries Authorization Bearer or X-Wingman-Access-Key, and NO X-* product credential headers.

    C->>S: POST /mcp · initialize
    S-->>C: 200 · server capabilities
    C->>S: POST /mcp · notifications/initialized
    C->>S: POST /mcp · tools/list
    S-->>C: 200 · tool catalogue (RAG + environment tools all listed)

    C->>S: POST /mcp · tools/call · name=search_uem_docs
    S->>V: vector similarity search (local, read-only)
    V-->>S: matching documents
    S-->>C: 200 · JSON search results

    Note over C,S: A tools/call for an environment tool (uem_*, horizon_*, …) returns HTTP 200 but a ToolError in the body — no credentials.
```

## What the third-party client must do

1. **Authenticate to the transport.** There is no unauthenticated MCP access.
   The client presents either an Entra ID `Authorization: Bearer <jwt>` token or
   the static `X-Wingman-Access-Key` header. Failing this returns `401`/`403`.
2. **Send no product credential headers.** The client omits all `X-UEM-*`,
   `X-Horizon-*`, `X-App-Volumes-*`, `X-Access-*`, etc. headers.
   `CredentialHeaderMiddleware` then produces an empty bundle
   (`_request_credentials = None`).
3. **Call only the `search_*` tools.** The four RAG tools below run without any
   credential check.

## The RAG tools and data stores

| Tool | Queries | Store |
|------|---------|-------|
| `search_uem_docs` | Workspace ONE UEM documentation | `~/.wingman-mcp/stores/uem/` |
| `search_api_reference` | REST API endpoint reference (per product) | `~/.wingman-mcp/stores/api/` |
| `search_release_notes` | Combined release notes (per product / version) | `~/.wingman-mcp/stores/release_notes/` |
| `search_omnissa_docs` | General Omnissa product docs (per product) | `~/.wingman-mcp/stores/<product>/` |

- The stores are **local Chroma vector databases** (SQLite-backed). Queries run
  entirely on the server with `sentence-transformers` (`all-MiniLM-L6-v2`)
  embeddings; no outbound API calls are made during a search.
- Content is populated ahead of time by the ingest pipeline, which scrapes the
  Omnissa `docs`, `developer`, and `techzone` sitemaps.
- Dispatch for these four tools lives in `wingman_mcp/server.py:1908`; none of
  them call `_require_auth()`. `search_uem_docs` additionally checks
  `stores_exist()` and reports if the index is missing.

## Limits of this model

- **No tool hiding.** A third-party client still *sees* the environment tools
  in `list_tools()`. It just cannot successfully *run* them without credentials.
- **The guard is the missing credentials, not a policy.** If the same client
  were ever given product credential headers, the environment tools would
  immediately become usable. Treat the credential headers as the actual
  security boundary.
- **Transport auth is shared.** The Entra token / static key that lets the
  client reach `/mcp` is the same one used for full-access clients; it does not
  by itself scope the client to RAG.
- For a server-enforced RAG-only guarantee (a dedicated scope, a per-client
  allowlist, or a RAG-only deployment mode), a code change would be required.
