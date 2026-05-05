# Multi-product RAG ingestion: release notes & API references

**Date:** 2026-04-25
**Status:** Approved design (pre-implementation)
**Scope:** wingman-mcp — RAG ingestion subsystem

## Goal

Extend the wingman-mcp RAG ingestion process so that release notes and REST
API documentation are searchable as first-class, per-product axes for the
full Omnissa product portfolio. Today both axes are UEM-only.

A user asking "what changed in App Volumes 2603?" or "what's the path for
the Horizon REST endpoint that creates a desktop pool?" should get focused,
product-scoped results from a dedicated MCP tool — not a best-effort hit
from a generic doc search.

## Non-goals

- Indexing customer-deployed live tenants for any product other than UEM.
  All non-UEM API specs are pulled from public sources (`developer.omnissa.com`).
- Cross-product unified search (a single "find anything" tool). Product
  scoping at search time is the design.
- Replacing the existing UEM `.txt` release-notes workflow. UEM stays as is;
  the new infrastructure runs alongside it.
- Re-ranking, hybrid search, or any retrieval-quality work. This spec is
  ingestion-shaped only.

## Final product registry

Ten first-class products. Each has up to three associated stores (docs,
release notes, API).

| Slug | Label | Docs store | RN | API spec source |
|---|---|---|---|---|
| `uem` | Workspace ONE UEM | yes (existing — narrows: Access & Intelligence move out) | local `.txt` workflow (existing) | live tenant Swagger (existing, `API_MAP`) |
| `horizon` | Omnissa Horizon | yes (existing) | docs.omnissa.com bundles | `developer.omnissa.com/horizon-apis/horizon-server/versions/2603/rest-api-swagger-docs.json` |
| `horizon_cloud` | Horizon Cloud Service | yes (existing) | docs.omnissa.com bundles | `developer.omnissa.com/horizon-apis/horizon-cloud-nextgen/horizon-cloud-nextgen-api-doc-public.yaml` |
| `app_volumes` | App Volumes | yes (existing) | docs.omnissa.com bundles | `developer.omnissa.com/app-volumes-apis/versions/2603/swagger.json` |
| `uag` | Unified Access Gateway | yes (existing) | docs.omnissa.com bundles | `developer.omnissa.com/uag-rest-apis/rest-api-swagger.json` |
| `dem` | Dynamic Environment Manager | yes (existing) | docs.omnissa.com bundles | — none (no API) |
| `thinapp` | ThinApp | yes (existing) | docs.omnissa.com bundles | — none (no API) |
| `access` | Workspace ONE Access | **new — splits out of UEM store** | docs.omnissa.com bundles | `developer.omnissa.com/omnissa-access-apis/openapi.json` |
| `intelligence` | Workspace ONE Intelligence | **new — splits out of UEM store** | docs.omnissa.com bundles (`IntelligenceRN`) | Intelligence PDF → text (`developer.omnissa.com/.../DHUB-APIDocumentationforOmnissaIntelligence-V2-130326-183145.pdf`) |
| `identity_service` | Omnissa Identity Service | **new — never indexed before** | docs.omnissa.com bundles (`identity-services-release-notes`) | `developer.omnissa.com/omnissa-identity-service-api/omnissa-identity-service-api-doc.json` |

**Notes**

- Hub stays family-merged into the UEM ecosystem store. Not promoted to a
  standalone product (out of scope for this work).
- Access and Intelligence split fully out of the UEM store. UEM's
  `_UEM_ALLOWED_FAMILIES` narrows to `{"uem", "hub"}`.
- `identity_service` is brand new — has its own docs/RN/API stores and
  registry entry.
- DEM and ThinApp get docs (existing) and RN (new) but no API.

## Storage & data model

### Stores on disk

```
~/.wingman-mcp/stores/
  uem/                    # docs (existing — narrows: Access/Intelligence move out)
  horizon/                # docs (existing)
  horizon_cloud/          # docs (existing)
  app_volumes/            # docs (existing)
  uag/                    # docs (existing)
  dem/                    # docs (existing)
  thinapp/                # docs (existing)
  access/                 # docs (NEW)
  intelligence/           # docs (NEW)
  identity_service/       # docs (NEW)
  release_notes/          # ONE combined RN store, all products (existing path, schema extended)
  api/                    # ONE combined API store, all products (existing path, schema extended)
```

One combined `release_notes` store and one combined `api` store, with
`product` as a metadata filter at search time. This matches today's pattern
(both stores already exist as singletons; we extend their schema).

Per-product RN/API stores were considered and rejected: they would multiply
Chroma instances unnecessarily and the search-time filter is cheap.

### Release-notes chunk metadata

| Field | Example | Notes |
|---|---|---|
| `product` | `"horizon"` | slug from registry — primary search-time filter |
| `product_label` | `"Omnissa Horizon"` | for display in tool output |
| `version` | `"2603"`, `"24.12"`, `"2506.1"`, `"2111.1"`, `"rolling"` | string, not normalized at write time — each product uses its native form |
| `bundle` | `"AppVolumesReleaseNotesV2603"` | docs bundle name (or `"uem-txt:v2602"` for UEM local files) |
| `source` | full URL or local path | |
| `section` | `"Windows Management"` | for UEM section-split chunks; `null` otherwise |
| `type` | `"release_notes"` | constant |

DEM versions are normalized at ingest time to drop the underscore
delimiters from the bundle name (e.g. `_2111.1_` → `2111.1`).

For products with rolling/unversioned RN (Horizon Cloud, Intelligence,
Identity Service), `version` is set to `"rolling"`.

### API-endpoint chunk metadata

| Field | Example | Notes |
|---|---|---|
| `product` | `"horizon"` | new — primary filter |
| `product_label` | `"Omnissa Horizon"` | |
| `api_group` | `"MAM V1"` (UEM) / `"horizon-server"` (others) | first OpenAPI tag, or spec name if no tags |
| `method`, `path`, `full_url`, `summary`, `operationId`, `tags` | (existing UEM fields) | preserved as-is |
| `version` | `"2603"` for versioned specs, `"rolling"` for unversioned | matches the RN convention |
| `source` | URL of OpenAPI spec | |
| `type` | `"api_endpoint"` | constant |

Intelligence's PDF-derived chunks have no path/method. They get
`type="api_documentation"` (already a recognised type by `search_api`'s
scoring), `product="intelligence"`, and a `section` from the PDF heading.

### Idempotent re-ingest

```python
# RN ingest, scoped per product per version:
db.delete(where={"$and": [{"product": slug}, {"version": v}]})

# API ingest, scoped per product:
db.delete(where={"product": slug})
```

Re-running `wingman-mcp ingest horizon_rn` only touches Horizon RN chunks;
other products in the combined store are untouched.

### Hash file (`.content-hashes.txt`)

Lives at `release_notes/.content-hashes.txt`. Schema extends from
`<version>=<sha>` to `<product>:<version>=<sha>`. Existing UEM-only entries
get migrated on first run by prefixing with `uem:`.

### Version conventions per product

| Product | Format on bundles | Notes |
|---|---|---|
| UEM | `2506`, `2509`, `2602` | yymm |
| Horizon | `V2603` etc. | yymm |
| Horizon Cloud | none | rolling — single canonical RN page; version `"rolling"` |
| App Volumes | `V2603`, `V2512` | yymm |
| UAG | `V2603`, `V2506.1` | yymm w/ optional patch |
| DEM | `_2111.1_` (underscore-delimited; **stripped** at ingest) | stored as `2111.1` |
| ThinApp | `V2603` | yymm |
| Access | `V24.12`, `V23.09`, `VSaaS` | dotted yy.mm |
| Intelligence | `IntelligenceRN` (single bundle, rolling) | version `"rolling"` |
| Identity Service | `identity-services-release-notes` (single bundle) | version `"rolling"` |

`version` is a free-form string; search filters on exact match (with
expansion — see Search section). UEM keeps its existing `int(v)` recency
sort; rolling-version chunks are excluded from that sort.

## Ingestion pipeline

Three new code paths, each with a single responsibility.

### 3a — Release-notes ingestion (`ingest_release_notes.py`, rewrite)

The current file is UEM-specific. It is replaced by a registry-driven
multi-product ingester that preserves UEM's local-`.txt` workflow as one
source-type among several.

`ProductConfig` gains an optional `release_notes` field:

```python
@dataclass
class ReleaseNotesSource:
    bundle_prefixes: list[str]              # e.g. ["AppVolumesReleaseNotes"]
    bundle_exact:    list[str] = []         # explicit bundle IDs to always include
    source_type:     Literal["docs_web", "uem_txt"] = "docs_web"
    version_re:      str = r"V(\d{4}(?:\.\d+)?)"
    section_splitter: Optional[Callable[[str], list[tuple[str, str]]]] = None
```

**Flow per product:**

1. **Discover RN bundles** — for `source_type="docs_web"`: walk
   docs.omnissa.com sitemaps and pick bundles matching `bundle_prefixes` or
   in `bundle_exact`. Reuse `_get_sub_sitemaps` / `_parse_sitemap` helpers.
2. **Download pages** — same `_extract_text` path as docs ingest (uses
   `docs-be.omnissa.com` API → clean topic_html).
3. **Extract version** — apply `version_re` against bundle name. DEM gets
   `r"_(\d{4}(?:\.\d+)?)_"`; the captured version is stored without
   underscores.
4. **Chunk** — `RecursiveCharacterTextSplitter(chunk_size=800,
   chunk_overlap=100)` (matches current UEM RN values; tighter than docs
   since RN entries are punchier).
5. **Tag metadata** — `product`, `product_label`, `version`, `bundle`,
   `source`, `type="release_notes"`.
6. **Idempotent write** — delete `(product, version)` then add.

UEM stays special — `source_type="uem_txt"` preserves the
`_find_rn_file()` logic with section splitting via `_split_by_sections()`.

For products with rolling/unversioned RN, `version_re` matches nothing →
version defaults to `"rolling"`.

### 3b — API ingestion (`ingest_api.py`, extend)

Existing UEM logic stays unchanged. New non-UEM path: fetch from URL,
handle JSON or YAML, walk OpenAPI 2.0 or 3.0 paths.

`ProductConfig` gains an optional `api` field:

```python
@dataclass
class ApiSource:
    spec_url:    str                                          # OpenAPI spec URL
    spec_format: Literal["openapi_json", "openapi_yaml", "pdf"]
    api_group:   str                                          # label for the api_group field
    version:     Optional[str] = None                         # e.g. "2603"; None → chunks tagged "rolling"
```

**Flow per non-UEM product:**

1. **Fetch spec** — `requests.get(spec_url, timeout=30)`. JSON via
   `.json()`; YAML via `pyyaml`.
2. **For OpenAPI (2 or 3)**: walk `data["paths"]`, extract
   `summary`/`description`/`operationId`/`tags`/`parameters`. Use
   `data.get("servers", [{}])[0].get("url")` for OpenAPI 3, fall back to
   `f"{schemes[0]}://{host}{basePath}"` for Swagger 2.
3. **Idempotent write** — `delete(where={"product": slug})` then add.

UEM keeps its `API_MAP`-driven live-tenant Swagger fetch unchanged. The
ingester branches: if `product == "uem"`, use the existing path; else, use
the new `ApiSource` path.

### 3c — PDF ingestion (`ingest_api_pdf.py`, NEW module)

Splits PDF handling out of `ingest_api.py` to keep that file focused on
Swagger/OpenAPI. Single responsibility:

```python
def ingest_pdf_api(product, source: ApiSource, store_dir, embeddings):
    # download → extract text per page → section-split → chunk → embed
```

PDF text extracted via `pypdf.PdfReader`. Section split on heading patterns
(regex against ALL CAPS headings or numbered section headers). Chunk with
`RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)`
(matches docs ingest — PDF prose chunks more like docs than RN).

Type stamps as `api_documentation` rather than `api_endpoint` so that
`search_api`'s existing scoring (which favours `api_endpoint`) still
prefers structured endpoints when both are present.

Adds new dependency: `pypdf`. Goes in `[ingest]` extras only — runtime
install is unaffected.

### 3d — Concurrency & rate-limiting

RN bundles are sparse (a few dozen pages per product max). Use
`ThreadPoolExecutor(max_workers=10)` for RN page fetches. API spec fetches
are per-product single requests — no concurrency needed.

### 3e — RN content also lives in product docs stores

Important note: `ingest_docs.py` already preserves release-notes bundles in
each product's docs store (via `_RELEASE_NOTES_BUNDLE_PATTERN`). After this
work, RN content lives in two places:

1. The product's docs store (via `ingest_docs.py` — preserved as today)
2. The combined `release_notes` store (via new `ingest_release_notes.py`)

**Decision: keep both.** Reasoning:

- Docs store gives general "what's in Horizon" search hits, including
  RN-as-context.
- RN store gives focused "what changed in 2603" search with version
  filtering.
- Removing RN bundles from product docs stores would weaken general-doc
  search (users asking "is X supported in 2603?" benefit from RN content).
- Storage cost is small (RN bundles are a tiny fraction of docs).

`search_omnissa_docs` continues to surface RN chunks (with `bundle_title`
containing "Release Notes"); `search_release_notes(product=...)` is the
focused tool.

## Search tool surface

Goal: small, backward-compatible additions. Don't add new tools; extend
existing ones with a `product` parameter. AI clients already know how to
use the existing tools; making `product` optional with sensible defaults
preserves muscle memory.

### Tool changes

| Tool | Change |
|---|---|
| `search_uem_docs` | **No signature change.** Description updated — drop "(Access, Hub, Intelligence)" since Access and Intelligence move out. Hub stays. The internal multi-family scoring branches for `access`/`intelligence` become dead but harmless (UEM store won't contain those families post-rebuild). |
| `search_omnissa_docs` | **No signature change.** Description's product enum gains `access`, `intelligence`, `identity_service`. |
| `search_release_notes` | **Adds optional `product` parameter** (string, default `"uem"`). When omitted, behaves exactly as today (UEM RN). When set, queries the combined RN store filtered to that product. Component-focused multi-pass searches (the "Windows Management"/"macOS Management" expansion) only fire for `product="uem"` since those headings are UEM-specific. |
| `search_api_reference` | **Adds optional `product` parameter** (string, default `"uem"`). When omitted, behaves as today. When set, scopes Chroma filter to `{"product": slug, "type": "api_endpoint"}` (or `api_documentation` for Intelligence's PDF chunks). |

### `search.py` internals

- `search_release_notes()` gains a `product` arg. Filter changes from
  `{"type": "release_notes"}` to
  `{"$and": [{"product": product}, {"type": "release_notes"}, {"version": {"$in": versions}}]}`
  (with version expansion — see below). Search prefix comes from
  `PRODUCTS[product].search_prefix` instead of hardcoded `"Workspace ONE
  UEM"`.
- `search_api()` gains a `product` arg. Filter scopes by product. The
  lexical fallback (`_lexical_api_fallback`) gains a product filter on its
  `db.get(where=...)` call.
- `search_uem()` and `search_product_docs()` unchanged.

### Version normalization

Different products store version strings in different forms (Access uses
`24.12`, others use `2412`-style). The dot vs no-dot distinction is usually
unknown to end users. Both search tools expand the user's version input
into a candidate set and filter with Chroma `$in`:

```python
def _expand_version(v: str) -> list[str]:
    """Expand a user-supplied version into all equivalent stored forms."""
    v = v.lower().lstrip("v").strip()
    candidates = {v, v.replace(".", "")}
    # 4-digit yymm input → add the dotted yy.mm form
    if re.fullmatch(r"\d{4}", v):
        candidates.add(f"{v[:2]}.{v[2:]}")
    # 5-6 digit input like '250601' → add yy.mm.patch form
    if re.fullmatch(r"\d{5,6}", v):
        candidates.add(f"{v[:2]}.{v[2:4]}.{v[4:]}")
    return sorted(candidates)
```

| User passes | Expanded set | Matches |
|---|---|---|
| `"2412"` | `{"2412", "24.12"}` | Access `V24.12` |
| `"24.12"` | `{"2412", "24.12"}` | Access `V24.12` |
| `"2603"` | `{"2603", "26.03"}` | Horizon/UEM/AppVol/etc. `2603` (`26.03` candidate just doesn't match anything stored) |
| `"2506.1"` | `{"2506.1", "25061"}` | UAG `2506.1` |
| `"v2602"` | `{"2602", "26.02"}` | UEM `2602` (existing `lstrip("v")` behavior preserved) |

**Limitation**: this does not auto-broaden `"2506"` to also match
`"2506.1"` — those are intentionally distinct releases (GA vs patch). To
ask about all 2506-line content, the caller omits `version` and lets the
recency scoring rank.

### Description copy (LLM-facing)

- `search_release_notes` — "Search Omnissa product release notes for
  feature changes, bug fixes, resolved issues, and new capabilities.
  Supports product filter (default: `uem`). Valid: `uem`, `horizon`,
  `horizon_cloud`, `app_volumes`, `uag`, `dem`, `thinapp`, `access`,
  `intelligence`, `identity_service`. Supports version filter where
  applicable (e.g. UEM `'2602'`, Horizon `'2603'`, Access `'24.12'`)."
- `search_api_reference` — "Search Omnissa REST API endpoint
  documentation. Supports product filter (default: `uem`). Valid: `uem`,
  `horizon`, `horizon_cloud`, `app_volumes`, `uag`, `access`,
  `intelligence`, `identity_service`. (DEM and ThinApp have no API.)"

### Validation

If a caller passes `product="dem"` or `product="thinapp"` to
`search_api_reference`, return a clear text error: *"DEM/ThinApp do not
have a REST API. Try `search_omnissa_docs` for product documentation."*

If a caller passes an unknown slug to either tool, list valid slugs in the
error message.

### `search_uem_docs` deprecation

Not deprecated. `search_uem_docs` is the canonical "ask about UEM" entry
point, has a tighter description, and is what existing AI tooling calls.
Keep both `search_uem_docs` and `search_omnissa_docs(product="uem")`
working.

## CLI, check command, migration

### CLI — `cli.py`

`cmd_ingest` already iterates `list_product_slugs()` and runs
`ingest_product` for each. Adding `access`, `intelligence`,
`identity_service` to the `PRODUCTS` dict makes them work automatically
for **docs** ingest. No `cli.py` changes needed for docs.

The ingest target vocabulary grows:

```
wingman-mcp ingest                                   # all (every product's docs + RN + API)
wingman-mcp ingest horizon                           # horizon docs only
wingman-mcp ingest horizon_rn                        # horizon release notes only
wingman-mcp ingest horizon_api                       # horizon API only
wingman-mcp ingest release_notes                     # ALL products' release notes
wingman-mcp ingest api                               # ALL products' API refs
wingman-mcp ingest docs                              # alias: every product's docs (existing)
wingman-mcp ingest rn                                # NEW alias: every product's RN
```

`get_store_keys()` in `config.py` stays as `(*products, "api",
"release_notes")` since the on-disk stores are unchanged. The `<slug>_rn`
and `<slug>_api` targets are routing labels only; they all write to the
same combined `release_notes` and `api` stores. Validation of these
synthetic targets lives in `cmd_ingest` / `cmd_check`.

`wingman-mcp ingest --list` updated:

```
Available stores:

  Product documentation:
    uem               Workspace ONE UEM
    horizon           Omnissa Horizon
    horizon_cloud     Horizon Cloud Service / DaaS
    app_volumes       App Volumes
    uag               Unified Access Gateway
    dem               Dynamic Environment Manager
    thinapp           ThinApp
    access            Workspace ONE Access
    intelligence      Workspace ONE Intelligence
    identity_service  Omnissa Identity Service

  Combined stores:
    api               REST API references — supports all products with APIs
    release_notes     Release notes — supports all products

  Per-product axes (writes to combined stores):
    <slug>_rn         e.g. horizon_rn — that product's release notes only
    <slug>_api        e.g. horizon_api — that product's API spec only
                      (DEM and ThinApp have no API and reject *_api targets)

  Aliases:
    docs              every product's documentation
    rn                every product's release notes
    all               everything (default when no targets given)
```

### `check` command (`check.py`)

Existing `check_product`, `check_api`, `check_release_notes` stay; each
grows multi-product awareness:

- `check_release_notes(targets)` — accepts an optional product list. For
  each requested product, finds expected RN bundles vs what's stored
  (filter Chroma by `product=slug`). Reports per-product diff. UEM keeps
  its `.txt`-vs-hash file content-change check.
- `check_api(targets)` — accepts an optional product list. For UEM,
  fetches live Swagger from each `API_MAP` URL (existing). For others,
  fetches the OpenAPI spec from `developer.omnissa.com`, walks paths,
  diffs against stored `(method, path)` tuples filtered by `product=slug`.
- `check_product` — unchanged.

`<slug>_rn` and `<slug>_api` targets get translated by `cmd_check` the
same way `cmd_ingest` translates them.

### Data migration plan (Access & Intelligence split-out)

The hard split (per Section 1) means the existing UEM store contains
chunks tagged `product_family: "access"` and `product_family:
"intelligence"` that need to leave. Path 1 (clean rebuild) is recommended.

**Path 1 — Clean rebuild.**

```bash
# 1. Code change: remove access & intelligence from _UEM_ALLOWED_FAMILIES.
# 2. Rebuild UEM docs from scratch (now narrower):
wingman-mcp ingest uem
# 3. Populate the three new docs stores:
wingman-mcp ingest access intelligence identity_service
# 4. Populate the combined RN/API stores:
wingman-mcp ingest rn api
```

Cost: full UEM re-embed (tens of minutes on a typical Mac). Acceptable for
a one-shot migration. Predictable, no leftover state.

Path 2 (surgical delete) — skipped. Per-chunk
`delete(where={"product_family": "access"})` followed by ingest of the new
stores is faster but risks missed chunks and embedding gaps. Not worth the
risk.

### Backward compatibility

- All existing tool calls keep working. The `product` parameter on
  `search_release_notes` / `search_api_reference` defaults to `"uem"`.
- Existing UEM RN `.txt` workflow preserved (paths, version map, hash
  file).
- `search_uem_docs` keeps working but returns less content (Access &
  Intelligence are gone). Users who want the old breadth call
  `search_omnissa_docs(product="access" | "intelligence", ...)`.
- Existing `ingest` / `check` invocations all keep working — only new
  targets are added.

### Documentation updates

- `README.md` — refresh "Stores" section, add new product table, document
  the per-product `_rn` / `_api` ingest targets.
- `INGEST_MACOS.md` — update to mention non-UEM products no longer need
  local `.txt` files (they're scraped from docs.omnissa.com).

## Testing approach

Unit tests for the pure logic, smoke tests for the network-bound paths.

- **Pure-logic units (unit-test)**:
  - `_expand_version` — table-driven test against the example inputs in
    the version-normalization section.
  - `version_re` extraction per product — feed bundle names from the
    product-version table; assert the extracted version matches expected
    (including the DEM underscore-strip).
  - OpenAPI walker — fixture small Swagger 2 and OpenAPI 3 documents,
    assert the right `(method, path, summary)` tuples emerge.
- **Network-bound paths (smoke test, gated behind a flag)**:
  - Fetch each non-UEM API spec URL, assert non-empty `data["paths"]`.
  - Hit the docs.omnissa.com sitemap, assert RN bundles for each product
    are discoverable.
- **Idempotency test** — ingest one product's RN twice in a row, assert
  the chunk count stays constant (delete-then-add semantics).
- **Migration smoke** — after running the Path-1 sequence on a test data
  dir, assert UEM store contains zero chunks with
  `product_family in {"access", "intelligence"}`.

## Rollout

After the implementation merges:

1. Operator runs the migration sequence in the "Data migration plan"
   section above. Single shell block, ~tens of minutes wall clock.
2. Operator validates with `wingman-mcp status` and a few sample
   `search_release_notes(product="horizon", version="2603")` calls.
3. Pre-built store distribution (when implemented in `cmd_setup`) ships
   the new layout transparently — users running `wingman-mcp setup` get
   the new stores without thinking about it.

## Open questions

- **API spec versioning over time**: Horizon and App Volumes URLs include
  `versions/2603/` segments. When 2606/2609 ship, the `ApiSource.spec_url`
  needs to bump. Two options for the future: (a) hardcode and bump
  manually each release (matches the current App Volumes
  `extra_bundles` pattern in `products.py`); (b) discover the latest
  version dynamically by scraping the parent index page. **Resolution
  deferred** — start with (a); revisit if it becomes burdensome.
- **Intelligence PDF refresh detection**: `check_api` for Intelligence
  needs a way to know when a new PDF is published. The PDF filename
  embeds a version (`V2-130326-183145`); the simplest check is to compare
  the latest filename on the developer.omnissa.com listing page against
  the one we have. **Resolution deferred** — out of scope for the initial
  implementation; the hash-file pattern from RN can be reused for
  content-change detection.

## Implementation plans

This spec is split into two implementation plans, written in order:

1. **Plan 1 — Release notes**: registry extension (3 new products + RN
   field), `ingest_release_notes.py` rewrite, `search_release_notes` tool
   change, `check_release_notes` extension, CLI updates, migration.
2. **Plan 2 — APIs**: `ingest_api.py` extension + `ingest_api_pdf.py`,
   `search_api_reference` tool change, `check_api` extension. Builds on
   the registry changes from Plan 1.

Plan 1 ships independently and delivers user value (RN search for the new
products) before Plan 2 lands.
