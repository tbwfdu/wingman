# Embedding Strategy

This describes how text is turned into vectors and how those vectors are
stored and queried. The embedding code lives in the public `wingman-mcp`
package (`embeddings.py`), and is shared by both the `wingman-mcp-server`
ingest pipeline and the query-time search path.

## Model

| Property | Value |
|---|---|
| Model | `all-MiniLM-L6-v2` |
| Library | `sentence-transformers` (HuggingFace) |
| Type | Local, self-hosted (no API calls, no API key) |
| Vector dimensions | 384 |
| Defined in | `wingman-mcp/src/wingman_mcp/embeddings.py` |

The model is loaded lazily on first use and cached in a module-level global
(`_get_model()`), so it is downloaded/initialized once per process.

## Why a local model

The same embedding function must run for both ingest and query, so the choice
is deliberately a small, fast, CPU-friendly model:

- No external embedding API, so no cost, no rate limits, and no network
  dependency at query time.
- `all-MiniLM-L6-v2` is small enough to embed quickly on CPU while still
  giving solid semantic retrieval quality.
- The same `LocalEmbeddings` class is used at ingest time and query time, so
  document vectors and query vectors always come from the identical model.

## Device selection

Embedding defaults to **CPU** for cross-platform reliability:

- The PyTorch MPS backend on Apple Silicon has had stability regressions
  (encoding can segfault mid-batch), so CPU is the safe default.
- Override with the `WINGMAN_MCP_EMBED_DEVICE` env var (e.g. `mps`, `cuda`)
  to opt in to GPU acceleration.

Two defensive env vars are set at import time, before `torch` /
`sentence-transformers` are imported:

- `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` avoids fork-after-Cocoa-init
  crashes on macOS.
- `TOKENIZERS_PARALLELISM=false` silences HuggingFace tokenizer warnings and
  avoids deadlocks when downstream code forks.

## LangChain / Chroma integration

`LocalEmbeddings` is a LangChain-compatible embedding class exposing the two
standard methods:

- `embed_documents(texts)` embeds a batch of chunks at ingest time.
- `embed_query(text)` embeds a single search query at query time.

Both call `SentenceTransformer.encode(...)` with `convert_to_numpy=True` and
return plain Python lists of floats.

## Ingest-time embedding

During ingest, the chunks for each product are embedded and written to a
Chroma vector store (`Chroma(persist_directory=..., embedding_function=embeddings)`).
To stay within Chroma's per-call limits, documents are added in batches:

- Batch size for `add_documents`: 5000 chunks per call
  (`chroma_limit` in `ingest_docs.py:333`).

## Query-time embedding and retrieval

At query time the same `LocalEmbeddings` instance embeds the search query, and
retrieval is done with Chroma `similarity_search` (cosine similarity over the
384-dimension vectors). The search layer over-fetches and then filters:

- Single-product / UEM searches request `k = max_results * 3` candidates
  before trimming (`search.py`).
- Filtered multi-product searches request `k = max_results * 2` and may run
  extra focused follow-up queries with smaller `k`.

Over-fetching gives the post-processing/filtering logic room to drop
off-product or low-quality hits while still returning a full result set.

## Summary

A single small local model, `all-MiniLM-L6-v2` via `sentence-transformers`,
produces 384-dimension vectors for both documents and queries. It defaults to
CPU for reliability (GPU is opt-in), is wrapped in a LangChain-compatible
`LocalEmbeddings` class, and feeds Chroma stores that are written in 5000-chunk
batches at ingest and queried with over-fetched `similarity_search` at runtime.
