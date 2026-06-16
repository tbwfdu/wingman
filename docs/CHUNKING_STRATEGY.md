# Chunking Strategy

The codebase uses two distinct chunking strategies, both in the
`wingman-mcp-server` package's ingest pipeline (the public `wingman-mcp`
package only queries the stores).

## 1. Endpoint-per-document (API specs, no text splitting)

For OpenAPI/Swagger API specs (`ingest_api.py`), each API endpoint becomes
**exactly one chunk**. No `RecursiveCharacterTextSplitter` is involved.
`_walk_openapi()` builds one `Document` per path/method, with
`type="api_endpoint"` metadata. The natural endpoint boundary *is* the chunk
boundary.

## 2. Recursive character splitting (prose docs: docs, release notes, PDF API docs)

Everything text-heavy uses LangChain's `RecursiveCharacterTextSplitter`, but
with different parameters and pre-segmentation per source type:

| Source | File | chunk_size | chunk_overlap | Pre-segmentation before splitting |
|---|---|---|---|---|
| Product docs (sitemap crawl) | `ingest_docs.py:236` | 2000 | 200 | none, `split_documents(all_docs)` |
| PDF API docs | `ingest_api_pdf.py:99` | 2000 | 200 | split into `(heading, body)` sections via `_split_pdf_sections()`, then split each body |
| Release notes | `ingest_release_notes.py:291` | 800 | 100 | UEM `.txt` notes get a custom `section_splitter` first |

### Key design details

- **Header/section prefixing for context retention.** Chunks aren't stored
  raw. Each prose chunk is prepended with contextual headers so the embedding
  (and the LLM at retrieval) keeps its bearings:
  - PDF: `f"{sec_name}\n\n{chunk}"` (`ingest_api_pdf.py:104`)
  - Release notes: `f"{header}\n\n{chunk}"` where header = bundle title +
    title + version (`ingest_release_notes.py:193`)

- **Two-level splitting for release notes.** Text is first cut into logical
  sections (web docs by topic, UEM `.txt` via a per-product `section_splitter`
  callback), then each section is character-split with the 800/100 splitter.
  Smaller chunks here because release notes are dense and version-scoped.

- **Idempotent re-ingest.** Before adding new chunks, existing ones are deleted
  by metadata scope (`product`, or `product` + `version`) so re-running ingest
  replaces rather than duplicates.

## Summary

Structure-aware segmentation first (headings/sections/endpoints), then
fixed-window recursive character splitting with overlap: 2000/200 for general
docs, 800/100 for release notes, and no splitting at all for API endpoints.
