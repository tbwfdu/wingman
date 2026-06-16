 # Wingman-MCP — Engineering Overview

**Wingman-MCP** is an internal [Model Context Protocol](https://modelcontextprotocol.io) server for Omnissa EUC. It gives AI assistants (Claude Desktop, Claude Code, etc.) two things: **semantic search over Omnissa product documentation** via a local RAG index, and **live, authenticated API access** to Workspace ONE UEM, Horizon, App Volumes, Workspace ONE Access, Omnissa Identity Service, and Horizon Cloud Service.

It exposes **82 tools** in total and can run fully local on an engineer's machine or as a shared, Entra-protected hosted service.

---

## 1. GitHub Repository

| | |
|---|---|
| **Repo** | `github.com/tbwfdu/wingman` (private) |
| **Clone (SSH)** | `git@github.com:tbwfdu/wingman.git` |
| **Default branch** | `main` (release-clean) · active development on `dev` |
| **Layout** | Monorepo containing three Python packages plus shared docs |

> Access is maintainer-restricted. Request access from the EUC tooling team.

---

## 2. Repository Structure

The repo was reorganised into a **three-package split** (v0.5.5) to separate the public tool layer from the private hosting and bridge components.

```
wingman/
├── wingman-mcp/          PUBLIC  — shared MCP tool layer + RAG search; runs locally over stdio
├── wingman-mcp-server/   PRIVATE — Streamable HTTP transport, Entra auth, OAuth shim, RAG ingestion
├── wingman-mcp-bridge/   PRIVATE — local stdio bridge to the remote hosted server
├── docs/                 Architecture & strategy docs
└── dist/                 Build artifacts
```

| Package | Visibility | Responsibility |
|---|---|---|
| **`wingman-mcp`** | Public | The 82 MCP tools, the RAG search layer, the embedding model, credential schema, and the local stdio server. Every other package depends on this. |
| **`wingman-mcp-server`** | Private | Hosted deployment: Streamable HTTP transport, Entra ID JWT authentication, the OAuth discovery/shim endpoints, and the **ingestion pipeline** that builds the RAG vector stores. |
| **`wingman-mcp-bridge`** | Private | A thin local stdio MCP server that forwards every request to the remote hosted server, keeping credentials in the OS keychain. |

Key source modules in `wingman-mcp/src/wingman_mcp/`: `server.py` (tool registry + dispatch), `search.py` (RAG retrieval), `embeddings.py` (local embedding model), and one `*_api.py` client per product (`uem_api.py`, `horizon_api.py`, `app_volumes_api.py`, `access_api.py`, `identity_service_api.py`, `horizon_cloud_api.py`).

---

## 3. Modes of Operation

Wingman-MCP runs in **three modes**, all serving the same 82-tool catalogue.

### Mode A — Local (stdio)
- **Command:** `wingman-mcp serve`
- Runs entirely on the engineer's machine over stdio. Nothing is sent to any hosted service.
- Documentation search needs no credentials. Live API tools use credentials stored in the engineer's **own OS keychain** (`wingman-mcp auth set --product <product>`).
- Best for individual engineers working in their editor / Claude Desktop.

### Mode B — Hosted (Streamable HTTP)
- **Command:** `wingman-mcp-server serve` (Azure Container Apps deployment in `wingman-mcp-server/http-deployment/`)
- MCP over Streamable HTTP on a single endpoint, `POST /mcp`.
- Every request must present an **Entra ID bearer token** or a **static fallback key** (`X-Wingman-Access-Key`); the server refuses to start if neither auth path is configured.
- Per-user product credentials travel in `X-*` request headers and are **never stored server-side**; identity and credentials are held only for the lifetime of a request.
- Publishes RFC 9728 / 8414 OAuth discovery metadata and an OAuth DCR shim so standard MCP clients can self-configure.

### Mode C — Bridge
- **Commands:** `wingman-mcp-bridge login` then `wingman-mcp-bridge link`
- A local stdio MCP server that transparently forwards to the **hosted** server over TLS.
- The Entra bearer token is obtained via a one-time browser sign-in and cached/refreshed in the OS keychain; per-tenant API credentials are read from the keychain and forwarded as `X-*` headers per request.
- Lets a Claude config stay a clean `command + args` one-liner with no secrets in `claude_desktop_config.json`.

---

## 4. Tools & Capabilities

**82 tools across 7 capability areas.** Documentation search requires no auth; all live API tools require per-product credentials. Mutating tools are marked *(mutation)*.

### 4.1 Documentation Search — Local RAG (4 tools, no auth)

| Tool | Description |
|---|---|
| `search_uem_docs` | Workspace ONE UEM product documentation (multi-family scoring) |
| `search_omnissa_docs` | Per-product docs for any of 20+ Omnissa product slugs (Horizon, App Volumes, UAG, DEM, Access, Intelligence, Identity Service, ThinApp, TechZone, …) |
| `search_api_reference` | REST API endpoint reference, scoped by `product` |
| `search_release_notes` | Release notes by version, scoped per product |

### 4.2 Workspace ONE UEM — Live API (37 tools)

| Area | Tools |
|---|---|
| **Environments** | `uem_list_environments` |
| **Devices** | `uem_search_devices`, `uem_get_device`, `uem_get_device_profiles`, `uem_get_device_apps`, `uem_get_device_security`, `uem_get_device_network`, `uem_send_device_command` *(mutation)* |
| **Users & Org Groups** | `uem_search_users`, `uem_get_user`, `uem_search_organization_groups`, `uem_get_organization_group`, `uem_get_og_children`, `uem_search_smart_groups` |
| **Profiles** | `uem_search_profiles`, `uem_get_profile`, `uem_create_profile` *(mutation)* |
| **Scripts** | `uem_search_scripts`, `uem_get_script`, `uem_create_script` *(mutation)*, `uem_create_script_from_json` *(mutation)* |
| **Sensors** | `uem_search_sensors`, `uem_get_sensor`, `uem_create_sensor` *(mutation)*, `uem_create_sensor_from_json` *(mutation)* |
| **Applications** | `uem_search_apps`, `uem_get_app`, `uem_download_app_blob` |
| **Compliance & Baselines** | `uem_search_compliance_policies`, `uem_get_baseline_templates`, `uem_search_baseline_policies`, `uem_get_baseline_policy` |
| **Export (backup)** | `uem_export_all` — timestamped dump of scripts/sensors/profiles/apps with `manifest.json` |
| **Migration** | `uem_migrate_scripts`, `uem_migrate_sensors`, `uem_migrate_profiles`, `uem_migrate_apps` — cross-environment, idempotent by name |

### 4.3 App Volumes — Live API (7 tools)
Session-cookie auth against an App Volumes Manager.

`app_volumes_search_applications`, `app_volumes_get_application`, `app_volumes_search_packages`, `app_volumes_get_package`, `app_volumes_search_writable_volumes`, `app_volumes_get_writable_volume`, `app_volumes_grow_writable_volume` *(mutation)*

### 4.4 Horizon (Connection Server) — Live API (10 tools)
Bearer-token auth against a Horizon Connection Server.

`horizon_search_desktop_pools`, `horizon_get_desktop_pool`, `horizon_search_farms`, `horizon_get_farm`, `horizon_search_machines`, `horizon_get_machine`, `horizon_search_sessions`, `horizon_get_session`, `horizon_disconnect_sessions` *(mutation)*, `horizon_restart_machines` *(mutation)*

### 4.5 Workspace ONE Access — Live API (7 tools)
OAuth client-credentials auth, per-tenant URL.

`access_search_users`, `access_get_user`, `access_search_groups`, `access_get_group`, `access_search_entitlements`, `access_get_activity_summary_report`, `access_create_user` *(mutation)*

### 4.6 Omnissa Identity Service — Live API (7 tools)
OAuth client-credentials auth, per-tenant URL; full SCIM 2.0.

`identity_service_search_users`, `identity_service_get_user`, `identity_service_search_groups`, `identity_service_get_group`, `identity_service_search_directories`, `identity_service_get_directory`, `identity_service_create_user` *(mutation)*

### 4.7 Horizon Cloud Service (Next-Gen) — Live API (10 tools, read-only)
OAuth client-credentials auth against the regional cloud URL; `org_id` auto-attached.

`horizon_cloud_search_pools`, `horizon_cloud_get_pool`, `horizon_cloud_search_templates`, `horizon_cloud_get_template`, `horizon_cloud_search_sessions`, `horizon_cloud_search_edge_deployments`, `horizon_cloud_get_edge_deployment`, `horizon_cloud_search_active_directories`, `horizon_cloud_search_uag_deployments`, `horizon_cloud_search_sso_configurations`

> Horizon Cloud mutations (provisioning, batch VM actions) are intentionally **not** exposed as tools.

---

## 5. RAG Pipeline — Chunking & Embedding

Documentation search is backed by local **Chroma** vector stores built by the ingestion pipeline in `wingman-mcp-server`. The full strategies are documented in the repo — engineers extending the index should read these first:

- **`docs/CHUNKING_STRATEGY.md`** — how source documents are segmented into chunks.
- **`docs/EMBEDDING_STRATEGY.md`** — how chunks are turned into vectors and stored/queried.

**Chunking (summary):** structure-aware segmentation first, then fixed-window recursive character splitting.

| Source | Chunk size / overlap | Notes |
|---|---|---|
| API specs (OpenAPI/Swagger) | one chunk per endpoint | No text splitting — the endpoint boundary *is* the chunk |
| Product docs (sitemap crawl) | 2000 / 200 | `RecursiveCharacterTextSplitter` |
| PDF API docs | 2000 / 200 | Pre-split into `(heading, body)` sections; heading prefixed onto each chunk |
| Release notes | 800 / 100 | Two-level: logical sections first, then character split; title/version prefixed |

Re-ingestion is idempotent — existing chunks are deleted by metadata scope before new ones are added.

**Embedding (summary):**

| Property | Value |
|---|---|
| Model | `all-MiniLM-L6-v2` (`sentence-transformers`) |
| Type | Local, self-hosted — no API calls, no key |
| Vector dimensions | 384 |
| Device | CPU by default (GPU opt-in via `WINGMAN_MCP_EMBED_DEVICE`) |
| Store | Chroma (SQLite-backed), written in 5000-chunk batches |
| Retrieval | Cosine `similarity_search` with over-fetching (`k = max_results x 2-3`) then filtering |

The same `LocalEmbeddings` class is used at both ingest and query time, so document and query vectors always come from the identical model.

---

## 6. Deployment & Operations

- **Hosted deployment:** Azure Container Apps. Infrastructure-as-code (`main.bicep`, `params.bicepparam`) and `deploy.sh` live in `wingman-mcp-server/http-deployment/`.
- **Building the RAG stores:** `wingman-mcp-server ingest` builds the vector stores; `wingman-mcp-server check` reports what a rebuild would change. See `INGEST_MACOS.md` for the incremental-refresh workflow and store sync to Azure Files.
- **Distribution of stores:** pre-built store archives are published to the repo Releases page; local users extract them into `~/.wingman-mcp/stores/`.

---

## 7. Further Reading (in-repo)

| Document | Covers |
|---|---|
| `docs/CHUNKING_STRATEGY.md` | RAG chunking strategy |
| `docs/EMBEDDING_STRATEGY.md` | Embedding model, vector store, retrieval |
| `docs/ARCHITECTURE_DIAGRAMS.md` | System architecture diagrams |
| `wingman-mcp-server/HTTP_FLOW.md` | HTTP transport request/response flow |
| `wingman-mcp-server/THIRD_PARTY_RAG_ACCESS.md` | RAG-only access flow for third-party clients |
| `wingman-mcp-server/INGEST_MACOS.md` | RAG ingestion / refresh workflow |
