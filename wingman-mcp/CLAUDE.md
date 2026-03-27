# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

An MCP (Model Context Protocol) server that exposes Workspace ONE UEM documentation search via local RAG. It provides three tools over stdio transport: `search_uem_docs`, `search_api_reference`, and `search_release_notes`.

## Build & Run Commands

```bash
# Activate virtualenv (Python 3.12)
source .venv/bin/activate

# Install in dev mode
pip install -e .

# Install with ingestion dependencies (needed for building stores)
pip install -e ".[ingest]"

# Build the wheel
python -m build

# Run the MCP server (stdio transport, used by MCP clients)
wingman-mcp serve

# Check store status (shows which RAG stores exist and their sizes)
wingman-mcp status

# Ingest all stores (requires [ingest] extras)
wingman-mcp ingest

# Ingest a single store
wingman-mcp ingest api
wingman-mcp ingest release_notes
wingman-mcp ingest uem

# Ingest with tuning params
wingman-mcp ingest uem --max-workers 50 --batch-size 500

# Copy built stores to dist and ~/.wingman-mcp/stores/
scripts/copy_stores.sh
scripts/copy_stores.sh uem   # single store
```

## Architecture

```
src/wingman_mcp/
├── cli.py           # Entry point (wingman-mcp command). Subcommands: serve, status, ingest, setup, auth
├── server.py        # MCP server. Registers tools, lazy-loads Chroma stores + auth, dispatches to search.py
├── search.py        # RAG search logic: search_uem(), search_api(), search_release_notes()
├── config.py        # Store path resolution. Reads WINGMAN_MCP_DATA_DIR env var, defaults to ~/.wingman-mcp/stores/
├── embeddings.py    # LocalEmbeddings wrapper around sentence-transformers (all-MiniLM-L6-v2)
├── credentials.py   # Credential storage: OS keychain (keyring) for secrets, config.json for URLs
├── auth.py          # OAuth 2.0 client_credentials flow, in-memory token cache with auto-refresh
└── ingest/          # Store builders (EXCLUDED from wheel distribution)
    ├── ingest_docs.py           # Crawls Omnissa sitemaps, fetches pages, chunks into UEM store
    ├── ingest_api.py            # Fetches Swagger JSON from UEM API help endpoints
    └── ingest_release_notes.py  # Parses v{version}_rn.txt files into release notes store
```

**Request flow:** MCP client → stdio → `server.py` (tool dispatch) → `search.py` (vector search + scoring) → ChromaDB → results as JSON

**Key design decisions:**
- Stores and embeddings are lazy-loaded on first tool call (not at server startup)
- The `ingest/` package is excluded from the distributed wheel — end users get pre-built stores
- Each search function over-fetches from Chroma (e.g. `k=max_results * 3`), then filters boilerplate, deduplicates, and re-ranks with custom scoring
- API search has a lexical fallback when vector search returns no results
- Store paths can be overridden per-store via `WINGMAN_MCP_STORE_{UEM|API|RELEASE_NOTES}_DIR` env vars
- UEM API auth uses OAuth 2.0 client_credentials. Secrets stored in OS keychain via `keyring`, non-secret URLs in `~/.wingman-mcp/config.json`. Env vars override stored values. `_get_auth()` in server.py returns a `UEMAuth` instance (or None) — future API tools call `auth.get_token()` for a bearer token

## Three RAG Stores

| Store | ChromaDB dir | Source | Chunk size |
|-------|-------------|--------|------------|
| `uem` | `stores/uem/` | Omnissa sitemaps (docs.omnissa.com) | 2000 chars |
| `api` | `stores/api/` | UEM Swagger JSON endpoints | 1 doc per endpoint |
| `release_notes` | `stores/release_notes/` | `v{version}_rn.txt` text files | 800 chars |

## Auth Commands

```bash
# Configure UEM API credentials (interactive, secrets go to OS keychain)
wingman-mcp auth set

# Show current auth configuration (secrets masked)
wingman-mcp auth status

# Test OAuth token fetch
wingman-mcp auth test

# Remove stored credentials
wingman-mcp auth clear
```

## Environment Variables

- `WINGMAN_MCP_DATA_DIR` — Base directory for all stores (default: `~/.wingman-mcp/stores/`)
- `WINGMAN_MCP_STORE_UEM_DIR` — Override path for UEM store only
- `WINGMAN_MCP_STORE_API_DIR` — Override path for API store only
- `WINGMAN_MCP_STORE_RELEASE_NOTES_DIR` — Override path for release notes store only
- `WINGMAN_MCP_CLIENT_ID` — OAuth client ID (overrides keychain)
- `WINGMAN_MCP_CLIENT_SECRET` — OAuth client secret (overrides keychain)
- `WINGMAN_MCP_TOKEN_URL` — OAuth token endpoint URL
- `WINGMAN_MCP_API_URL` — UEM API base URL
