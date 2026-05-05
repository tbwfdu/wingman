# Multi-product API References Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make REST API documentation a first-class, per-product searchable axis for every Omnissa product that publishes an OpenAPI spec — extending the UEM-only `ingest_api.py` to fetch and embed OpenAPI/Swagger documents from `developer.omnissa.com` for Horizon, Horizon Cloud, App Volumes, UAG, Access, Identity Service, and Intelligence (PDF).

**Architecture:** One combined `api` Chroma store, with `product` metadata as the search-time filter. Each `ProductConfig` gains an optional `ApiSource` describing the spec URL and format. UEM keeps its existing live-tenant `API_MAP` ingest path unchanged. Non-UEM products fetch their public OpenAPI spec from `developer.omnissa.com`, parse JSON or YAML, and walk `paths` to produce one Document per (method, path) tuple. Intelligence is a PDF — handled by a separate `ingest_api_pdf.py` module that produces unstructured prose chunks tagged `type="api_documentation"` rather than `api_endpoint`.

**Tech Stack:** Python 3.10+, `requests`, `pyyaml` (new dep), `pypdf` (new dep), langchain-chroma, pytest.

**Spec:** `docs/superpowers/specs/2026-04-25-multi-product-rag-ingest-design.md`

**Depends on:** Plan 1 — Multi-product Release Notes (for `ProductConfig` registry shape, the `<slug>_rn` / `<slug>_api` CLI vocabulary scaffolding, and the version-expansion helper). **Plan 2 will not work without Plan 1 merged first.**

---

## File Map

**Create:**
- `src/wingman_mcp/ingest/ingest_api_pdf.py` — Intelligence PDF → text → embed
- `tests/test_products_api_config.py` — registry shape assertions for `api` field
- `tests/test_openapi_walker.py` — table-driven OpenAPI 2/3 path walker tests
- `tests/test_api_pdf_helpers.py` — section-split unit tests for PDF text

**Modify:**
- `pyproject.toml` — add `pyyaml` and `pypdf` to `[ingest]` extras
- `src/wingman_mcp/ingest/products.py` — add `ApiSource` dataclass; attach `api` config to 7 products
- `src/wingman_mcp/ingest/ingest_api.py` — add multi-product OpenAPI fetch path; preserve existing UEM `API_MAP` path
- `src/wingman_mcp/ingest/check.py` — extend `check_api` to per-product
- `src/wingman_mcp/search.py` — `search_api` gains `product` parameter
- `src/wingman_mcp/server.py` — `search_api_reference` tool gains `product` input + updated description
- `src/wingman_mcp/cli.py` — wire `<slug>_api` and `api` alias routing (Plan 1 added `<slug>_rn`; this task mirrors it for API)
- `README.md` — refresh API store description

---

## Task 1: Add `pyyaml` and `pypdf` to ingest extras

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Append to the `[ingest]` extras**

```toml
ingest = [
    "requests",
    "beautifulsoup4",
    "tqdm",
    "python-dotenv",
    "pyyaml>=6.0",
    "pypdf>=4.0.0",
]
```

- [ ] **Step 2: Reinstall extras**

```bash
pip install -e '.[dev,ingest]'
```

Expected: pyyaml and pypdf install successfully.

- [ ] **Step 3: Smoke-import**

```bash
python -c "import yaml, pypdf; print('OK')"
```

Expected: prints OK.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "Add pyyaml and pypdf to [ingest] extras for multi-product API ingest"
```

---

## Task 2: Add `ApiSource` dataclass and `ProductConfig.api` field

**Files:**
- Modify: `src/wingman_mcp/ingest/products.py`
- Create: `tests/test_products_api_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_products_api_config.py`:

```python
"""Smoke tests on the api configuration shape."""
import pytest

from wingman_mcp.ingest.products import (
    ApiSource,
    PRODUCTS,
    ProductConfig,
)


def test_api_source_defaults():
    src = ApiSource(spec_url="https://example/spec.json", api_group="grp")
    assert src.spec_format == "openapi_json"
    assert src.version is None


def test_product_config_accepts_api():
    cfg = ProductConfig(
        slug="foo",
        label="Foo",
        description="",
        api=ApiSource(spec_url="https://example/spec.json", api_group="grp"),
    )
    assert cfg.api is not None
    assert cfg.api.spec_url == "https://example/spec.json"


def test_product_config_api_default_none():
    cfg = ProductConfig(slug="foo", label="Foo", description="")
    assert cfg.api is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_products_api_config.py -v
```

Expected: ImportError on `ApiSource`.

- [ ] **Step 3: Add the dataclass and field**

In `src/wingman_mcp/ingest/products.py`, just below the `ReleaseNotesSource` dataclass (added by Plan 1), insert:

```python
@dataclass
class ApiSource:
    """Where and how to fetch a product's REST API specification."""
    spec_url:    str
    api_group:   str
    spec_format: Literal["openapi_json", "openapi_yaml", "pdf"] = "openapi_json"
    version:     Optional[str] = None
```

In `ProductConfig`, add a new field at the end (after `release_notes`):

```python
    api: Optional[ApiSource] = None
```

- [ ] **Step 4: Re-run tests**

```bash
pytest tests/test_products_api_config.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/ingest/products.py tests/test_products_api_config.py
git commit -m "Add ApiSource dataclass and ProductConfig.api field"
```

---

## Task 3: Wire up `api` config for the 7 products that have APIs

**Files:**
- Modify: `src/wingman_mcp/ingest/products.py`
- Modify: `tests/test_products_api_config.py`

- [ ] **Step 1: Extend the test for per-product API config**

Append to `tests/test_products_api_config.py`:

```python
_PRODUCTS_WITH_API = [
    "horizon",
    "horizon_cloud",
    "app_volumes",
    "uag",
    "access",
    "intelligence",
    "identity_service",
]

_PRODUCTS_WITHOUT_API = ["dem", "thinapp"]


@pytest.mark.parametrize("slug", _PRODUCTS_WITH_API)
def test_product_has_api(slug):
    cfg = PRODUCTS[slug]
    assert cfg.api is not None, f"{slug} should have an api config"
    assert cfg.api.spec_url.startswith("https://"), f"{slug} api spec_url is not https"
    assert cfg.api.api_group, f"{slug} api_group must not be empty"


@pytest.mark.parametrize("slug", _PRODUCTS_WITHOUT_API)
def test_product_without_api(slug):
    cfg = PRODUCTS[slug]
    assert cfg.api is None, f"{slug} must not have an api config (no REST API)"


def test_uem_keeps_legacy_api_map_path():
    """UEM does not use the new ApiSource — its API ingest is API_MAP-driven."""
    cfg = PRODUCTS["uem"]
    assert cfg.api is None


def test_intelligence_uses_pdf_format():
    cfg = PRODUCTS["intelligence"]
    assert cfg.api.spec_format == "pdf"


def test_horizon_cloud_uses_yaml_format():
    cfg = PRODUCTS["horizon_cloud"]
    assert cfg.api.spec_format == "openapi_yaml"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_products_api_config.py -v
```

Expected: tests for all 7 API products fail.

- [ ] **Step 3: Attach `api=` to each product**

In `src/wingman_mcp/ingest/products.py`, add `api=...` arguments to:

For `"horizon"`:

```python
        api=ApiSource(
            spec_url="https://developer.omnissa.com/horizon-apis/horizon-server/versions/2603/rest-api-swagger-docs.json",
            api_group="horizon-server",
            spec_format="openapi_json",
            version="2603",
        ),
```

For `"horizon_cloud"`:

```python
        api=ApiSource(
            spec_url="https://developer.omnissa.com/horizon-apis/horizon-cloud-nextgen/horizon-cloud-nextgen-api-doc-public.yaml",
            api_group="horizon-cloud-nextgen",
            spec_format="openapi_yaml",
        ),
```

For `"app_volumes"`:

```python
        api=ApiSource(
            spec_url="https://developer.omnissa.com/app-volumes-apis/versions/2603/swagger.json",
            api_group="app-volumes",
            spec_format="openapi_json",
            version="2603",
        ),
```

For `"uag"`:

```python
        api=ApiSource(
            spec_url="https://developer.omnissa.com/uag-rest-apis/rest-api-swagger.json",
            api_group="uag",
            spec_format="openapi_json",
        ),
```

For `"access"`:

```python
        api=ApiSource(
            spec_url="https://developer.omnissa.com/omnissa-access-apis/openapi.json",
            api_group="omnissa-access",
            spec_format="openapi_json",
        ),
```

For `"intelligence"`:

```python
        api=ApiSource(
            spec_url="https://developer.omnissa.com/omnissa-intelligence-apis/guides/DHUB-APIDocumentationforOmnissaIntelligence-V2-130326-183145.pdf",
            api_group="omnissa-intelligence",
            spec_format="pdf",
        ),
```

For `"identity_service"`:

```python
        api=ApiSource(
            spec_url="https://developer.omnissa.com/omnissa-identity-service-api/omnissa-identity-service-api-doc.json",
            api_group="omnissa-identity-service",
            spec_format="openapi_json",
        ),
```

- [ ] **Step 4: Re-run tests**

```bash
pytest tests/test_products_api_config.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/ingest/products.py tests/test_products_api_config.py
git commit -m "Wire ApiSource config for 7 products with public OpenAPI specs"
```

---

## Task 4: Add a registry-driven OpenAPI walker to `ingest_api.py`

**Files:**
- Modify: `src/wingman_mcp/ingest/ingest_api.py`
- Create: `tests/test_openapi_walker.py`

This task is the heart of Plan 2: take an OpenAPI 2 or 3 document (JSON or
YAML), walk its `paths`, and emit one Document per (method, path) tuple.

- [ ] **Step 1: Write table-driven tests for the walker**

Create `tests/test_openapi_walker.py`:

```python
"""Tests for the OpenAPI 2/3 walker used by multi-product API ingest."""
from langchain_core.documents import Document

from wingman_mcp.ingest.ingest_api import _walk_openapi


_OPENAPI_3_FIXTURE = {
    "openapi": "3.0.1",
    "servers": [{"url": "https://example.com/api/v1"}],
    "paths": {
        "/foo/{id}": {
            "get": {
                "summary": "Get a foo",
                "description": "Returns the foo by id.",
                "operationId": "getFoo",
                "tags": ["Foo"],
                "parameters": [{"name": "id", "in": "path", "required": True}],
            },
        },
        "/bar": {
            "post": {"summary": "Create a bar", "tags": ["Bar"]},
        },
    },
}


_SWAGGER_2_FIXTURE = {
    "swagger": "2.0",
    "schemes": ["https"],
    "host": "host.example.com",
    "basePath": "/api/v2",
    "paths": {
        "/baz": {
            "get": {"summary": "List bazzes"},
        },
    },
}


def test_walk_openapi_3_extracts_servers_url():
    docs = _walk_openapi(_OPENAPI_3_FIXTURE, product="horizon", api_group="horizon-server")
    full_urls = [d.metadata["full_url"] for d in docs]
    assert "https://example.com/api/v1/foo/{id}" in full_urls
    assert "https://example.com/api/v1/bar" in full_urls


def test_walk_openapi_2_falls_back_to_host_basepath():
    docs = _walk_openapi(_SWAGGER_2_FIXTURE, product="uag", api_group="uag")
    assert any(
        d.metadata["full_url"] == "https://host.example.com/api/v2/baz"
        for d in docs
    )


def test_walk_openapi_emits_one_doc_per_method():
    docs = _walk_openapi(_OPENAPI_3_FIXTURE, product="horizon", api_group="horizon-server")
    assert len(docs) == 2
    methods = {d.metadata["method"] for d in docs}
    assert methods == {"GET", "POST"}


def test_walk_openapi_metadata_includes_product_and_type():
    docs = _walk_openapi(_OPENAPI_3_FIXTURE, product="horizon", api_group="horizon-server")
    for d in docs:
        assert d.metadata["product"] == "horizon"
        assert d.metadata["type"] == "api_endpoint"
        assert d.metadata["api_group"] == "horizon-server"


def test_walk_openapi_ignores_non_method_keys():
    spec = {
        "openapi": "3.0.0",
        "servers": [{"url": ""}],
        "paths": {
            "/x": {
                "parameters": [],  # not a method
                "get": {"summary": "g"},
            },
        },
    }
    docs = _walk_openapi(spec, product="p", api_group="g")
    methods = [d.metadata["method"] for d in docs]
    assert methods == ["GET"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_openapi_walker.py -v
```

Expected: ImportError on `_walk_openapi`.

- [ ] **Step 3: Add `_walk_openapi` and the multi-product entry point to `ingest_api.py`**

Append to `src/wingman_mcp/ingest/ingest_api.py` (below the existing UEM-specific helpers):

```python
# ---------------------------------------------------------------------------
# Multi-product OpenAPI walker (Plan 2)
# ---------------------------------------------------------------------------

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options", "trace"}


def _resolve_base_url(spec: dict) -> str:
    """Resolve the API base URL from an OpenAPI 2 or 3 document."""
    # OpenAPI 3 — `servers[0].url`
    servers = spec.get("servers")
    if servers and isinstance(servers, list):
        url = (servers[0] or {}).get("url") or ""
        return url.rstrip("/")
    # Swagger 2 — schemes + host + basePath
    schemes = spec.get("schemes") or []
    host = spec.get("host") or ""
    basepath = (spec.get("basePath") or "").rstrip("/")
    if host:
        scheme = (schemes[0] if schemes else "https")
        return f"{scheme}://{host}{basepath}"
    return ""


def _walk_openapi(spec: dict, product: str, api_group: str,
                  source_url: str = "", version: str | None = None) -> list[Document]:
    """Walk an OpenAPI 2 or 3 document; emit one Document per (method, path) tuple."""
    from wingman_mcp.ingest.products import PRODUCTS
    label = PRODUCTS[product].label if product in PRODUCTS else product
    base = _resolve_base_url(spec)
    docs: list[Document] = []
    for path, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            full_url = f"{base}{path}" if base else path
            summary = op.get("summary", "") or ""
            description = op.get("description", "") or ""
            operation_id = op.get("operationId", "") or ""
            tags = ", ".join(op.get("tags", []) or [])
            content = (
                f"{label} API Endpoint\n"
                f"Category: {api_group}\n"
                f"Full URL: {full_url}\n"
                f"Path: {path}\n"
                f"Method: {method.upper()}\n"
                f"Summary: {summary}\n"
                f"Description: {description}\n"
                f"OperationId: {operation_id}\n"
                f"Tags: {tags}"
            )
            docs.append(Document(
                page_content=content.strip(),
                metadata={
                    "product": product,
                    "product_label": label,
                    "source": source_url,
                    "full_url": full_url,
                    "path": path,
                    "method": method.upper(),
                    "type": "api_endpoint",
                    "api_group": api_group,
                    "version": version or "rolling",
                },
            ))
    return docs


def _fetch_spec(url: str, fmt: str) -> dict:
    """Fetch and parse an OpenAPI spec from a URL."""
    res = requests.get(url, timeout=30, headers={"User-Agent": "WingmanMCP/1.0"})
    res.raise_for_status()
    if fmt == "openapi_json":
        return res.json()
    elif fmt == "openapi_yaml":
        import yaml
        return yaml.safe_load(res.text)
    raise ValueError(f"Unsupported spec format: {fmt}")


def ingest_api_for_product(slug: str, store_dir: str, embeddings):
    """Ingest one product's API spec into the combined `api` store."""
    from wingman_mcp.ingest.products import PRODUCTS

    cfg = PRODUCTS.get(slug)
    if cfg is None:
        raise ValueError(f"Unknown product: {slug}")
    if cfg.api is None:
        print(f"  {slug} has no api config — skipping.")
        return

    os.makedirs(store_dir, exist_ok=True)
    vectorstore = Chroma(persist_directory=store_dir, embedding_function=embeddings)

    print(f"\n=== Ingesting API for {slug} from {cfg.api.spec_url} ===")

    if cfg.api.spec_format == "pdf":
        # Defer to ingest_api_pdf — keeps PDF concerns isolated.
        from wingman_mcp.ingest.ingest_api_pdf import ingest_pdf_api
        ingest_pdf_api(cfg, vectorstore)
        return

    try:
        spec = _fetch_spec(cfg.api.spec_url, cfg.api.spec_format)
    except Exception as e:
        print(f"  Failed to fetch/parse spec: {e}")
        return

    docs = _walk_openapi(
        spec,
        product=slug,
        api_group=cfg.api.api_group,
        source_url=cfg.api.spec_url,
        version=cfg.api.version,
    )
    if not docs:
        print(f"  No paths found in {slug} spec.")
        return

    # Idempotent: drop existing chunks for this product before adding.
    try:
        existing = vectorstore.get(where={"product": slug})
        existing_ids = existing.get("ids", [])
        if existing_ids:
            vectorstore.delete(ids=existing_ids)
    except Exception as e:
        print(f"  ({slug}) cleanup skipped: {e}")

    vectorstore.add_documents(docs)
    print(f"  Added {len(docs)} endpoints for {slug}.")
```

(Note: keep the existing `ingest_api(store_dir, embeddings)` function — it
remains the UEM-only `API_MAP` path. Don't delete or rename it.)

- [ ] **Step 4: Re-run tests**

```bash
pytest tests/test_openapi_walker.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/ingest/ingest_api.py tests/test_openapi_walker.py
git commit -m "Add multi-product OpenAPI walker; ingest_api_for_product entry point"
```

---

## Task 5: Add `ingest_api_pdf.py` for Intelligence

**Files:**
- Create: `src/wingman_mcp/ingest/ingest_api_pdf.py`
- Create: `tests/test_api_pdf_helpers.py`

- [ ] **Step 1: Write tests for the section splitter**

Create `tests/test_api_pdf_helpers.py`:

```python
"""Tests for the PDF section splitter used by Intelligence API ingest."""
from wingman_mcp.ingest.ingest_api_pdf import _split_pdf_sections


def test_split_pdf_sections_uppercase_headings():
    text = (
        "INTRODUCTION\n"
        "This is the intro paragraph.\n\n"
        "AUTHENTICATION\n"
        "Use OAuth tokens.\n"
    )
    sections = _split_pdf_sections(text)
    assert sections == [
        ("INTRODUCTION", "This is the intro paragraph."),
        ("AUTHENTICATION", "Use OAuth tokens."),
    ]


def test_split_pdf_sections_numbered_headings():
    text = (
        "1. Overview\n"
        "Some prose.\n\n"
        "2. Endpoints\n"
        "More prose.\n"
    )
    sections = _split_pdf_sections(text)
    names = [s[0] for s in sections]
    assert names == ["1. Overview", "2. Endpoints"]


def test_split_pdf_sections_handles_no_headings():
    """Text without any heading produces a single 'General' section."""
    text = "Just some flat content with no headings at all.\n"
    sections = _split_pdf_sections(text)
    assert len(sections) == 1
    assert sections[0][0] == "General"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_api_pdf_helpers.py -v
```

Expected: ImportError.

- [ ] **Step 3: Create `ingest_api_pdf.py`**

```python
"""PDF API documentation ingest (Intelligence's developer.omnissa.com PDF).

Kept separate from `ingest_api.py` so that file stays focused on
Swagger/OpenAPI walking. PDF chunks are tagged `type="api_documentation"`
rather than `api_endpoint` because they have no structured method/path —
this lets `search_api`'s scoring still prefer structured endpoints when
both are present in results.
"""
from __future__ import annotations

import io
import re

import requests
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from wingman_mcp.ingest.products import ProductConfig

USER_AGENT = "WingmanMCP/1.0"

_HEADING_PATTERNS = [
    re.compile(r"^[A-Z][A-Z0-9 \-/]{2,}$"),       # ALL CAPS at least 3 chars
    re.compile(r"^\d+(\.\d+)?\.?\s+[A-Z].+$"),    # "1. Overview" / "2.1 Endpoints"
]


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    return any(p.match(s) for p in _HEADING_PATTERNS)


def _split_pdf_sections(text: str) -> list[tuple[str, str]]:
    """Split PDF text into (heading, body) pairs.

    A line matching any heading pattern starts a new section. Text before
    the first heading goes into a 'General' section.
    """
    sections: list[tuple[str, str]] = []
    current_name = "General"
    current_body: list[str] = []
    saw_heading = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if _is_heading(line):
            if current_body:
                sections.append((current_name, "\n".join(current_body).strip()))
            current_name = line.strip()
            current_body = []
            saw_heading = True
        else:
            current_body.append(line)
    if current_body:
        sections.append((current_name, "\n".join(current_body).strip()))
    # Strip empty bodies; keep at least one section.
    sections = [(n, b) for (n, b) in sections if b]
    if not sections:
        return [("General", text.strip())]
    if not saw_heading and sections[0][0] != "General":
        sections[0] = ("General", sections[0][1])
    return sections


def _extract_pdf_text(url: str) -> str:
    """Download a PDF and extract its text page-by-page."""
    from pypdf import PdfReader

    res = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT})
    res.raise_for_status()
    reader = PdfReader(io.BytesIO(res.content))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(pages)


def ingest_pdf_api(product: ProductConfig, vectorstore: Chroma) -> None:
    """Ingest one product's PDF API doc into the combined `api` store."""
    api = product.api
    assert api is not None and api.spec_format == "pdf"

    print(f"  Fetching PDF: {api.spec_url}")
    try:
        text = _extract_pdf_text(api.spec_url)
    except Exception as e:
        print(f"  Failed to download/parse PDF: {e}")
        return
    if not text.strip():
        print("  PDF text extraction returned no content.")
        return

    sections = _split_pdf_sections(text)
    splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)
    docs: list[Document] = []
    for sec_name, sec_text in sections:
        for chunk in splitter.split_text(sec_text):
            docs.append(Document(
                page_content=f"{sec_name}\n\n{chunk}",
                metadata={
                    "product": product.slug,
                    "product_label": product.label,
                    "source": api.spec_url,
                    "section": sec_name,
                    "type": "api_documentation",
                    "api_group": api.api_group,
                    "version": api.version or "rolling",
                },
            ))

    # Idempotent: drop existing chunks for this product before adding.
    try:
        existing = vectorstore.get(where={"product": product.slug})
        existing_ids = existing.get("ids", [])
        if existing_ids:
            vectorstore.delete(ids=existing_ids)
    except Exception as e:
        print(f"  ({product.slug}) cleanup skipped: {e}")

    vectorstore.add_documents(docs)
    print(f"  Added {len(docs)} PDF chunks for {product.slug}.")
```

- [ ] **Step 4: Re-run tests**

```bash
pytest tests/test_api_pdf_helpers.py -v
```

Expected: all 3 pass.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/ingest/ingest_api_pdf.py tests/test_api_pdf_helpers.py
git commit -m "Add ingest_api_pdf for Intelligence PDF API documentation"
```

---

## Task 6: Extend `search_api` with `product` parameter

**Files:**
- Modify: `src/wingman_mcp/search.py`

- [ ] **Step 1: Replace the body of `search_api`**

In `src/wingman_mcp/search.py`, replace the existing `search_api` function with:

```python
def search_api(
    query: str,
    db: Chroma,
    product: str = "uem",
    max_results: int = 10,
) -> List[Dict[str, str]]:
    """Search the API endpoint reference store, scoped to one product.

    Defaults to product='uem' so existing callers keep working unchanged.
    """
    from wingman_mcp.ingest.products import PRODUCTS

    if product not in PRODUCTS:
        return [{
            "content": f"Unknown product '{product}'. Valid: {', '.join(sorted(PRODUCTS))}",
            "source_url": "",
            "source": "wingman-mcp",
            "section": "error",
        }]

    cfg = PRODUCTS[product]
    if product != "uem" and cfg.api is None:
        return [{
            "content": (
                f"{cfg.label} does not have a REST API. "
                f"Try search_omnissa_docs(product='{product}') for product documentation."
            ),
            "source_url": "",
            "source": "wingman-mcp",
            "section": "no_api",
        }]

    search_prefix = cfg.search_prefix or cfg.label
    search_query = f"{search_prefix} API {query}".strip()

    base_filter = {"$and": [
        {"product": product},
        {"type": "api_endpoint"},
    ]}
    docs = db.similarity_search(search_query, k=max_results * 2, filter=base_filter)

    if not docs:
        docs = _lexical_api_fallback(db, query, product=product, limit=max_results)

    # Pull in api_documentation context (Intelligence's PDF chunks live here).
    context_docs = []
    for doc_type in ("api_documentation", "api_definition"):
        try:
            context_docs.extend(db.similarity_search(
                search_query, k=6,
                filter={"$and": [{"product": product}, {"type": doc_type}]},
            ))
        except Exception:
            pass

    combined = docs + context_docs
    filtered = [d for d in combined if not _is_boilerplate(d)]
    deduped = _dedup(filtered)

    def score(doc):
        meta = getattr(doc, "metadata", {}) or {}
        s = 0
        if meta.get("type") == "api_endpoint":
            s += 60
        elif meta.get("type") in {"api_definition", "api_documentation"}:
            s += 30
        return s

    deduped.sort(key=score, reverse=True)
    return _format_results(deduped[:max_results])
```

- [ ] **Step 2: Update `_lexical_api_fallback` to accept and apply `product`**

Replace the existing `_lexical_api_fallback` with:

```python
def _lexical_api_fallback(
    db: Chroma,
    query: str,
    product: str = "uem",
    limit: int = 8,
) -> List[Any]:
    token_set = set(_keyword_tokens(query))
    if not token_set:
        return []

    try:
        payload = db.get(where={"$and": [
            {"product": product},
            {"type": "api_endpoint"},
        ]})
    except Exception:
        return []

    metadatas = payload.get("metadatas", []) or []
    documents = payload.get("documents", []) or []

    scored: List[Tuple[int, Any]] = []
    for idx, meta in enumerate(metadatas):
        doc_text = (documents[idx] if idx < len(documents) else "") or ""
        haystack = " ".join([
            doc_text.lower(),
            str(meta.get("path", "")).lower(),
            str(meta.get("full_url", "")).lower(),
            str(meta.get("method", "")).lower(),
            str(meta.get("api_group", "")).lower(),
        ])
        s = sum(3 if t in haystack else 0 for t in token_set)
        if meta.get("method", "").lower() in token_set:
            s += 4
        if s > 0:
            scored.append((s, Document(page_content=doc_text, metadata=meta)))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [doc for _, doc in scored[:limit]]
```

- [ ] **Step 3: Run all tests**

```bash
pytest -v
```

Expected: all green (no test specifically exercises `search_api` here — the change is wiring; tested manually in Task 10).

- [ ] **Step 4: Commit**

```bash
git add src/wingman_mcp/search.py
git commit -m "Extend search_api with product parameter and product-scoped lexical fallback"
```

---

## Task 7: Update `server.py` — `search_api_reference` tool gains `product`

**Files:**
- Modify: `src/wingman_mcp/server.py`

- [ ] **Step 1: Update the tool definition**

Find the `Tool(name="search_api_reference", ...)` block. Replace its `description` and `inputSchema` with:

```python
    Tool(
        name="search_api_reference",
        description=(
            "Search Omnissa REST API endpoint documentation. "
            "Supports product filter (default: 'uem'). Valid products: "
            "uem, horizon, horizon_cloud, app_volumes, uag, access, "
            "intelligence, identity_service. (DEM and ThinApp have no API.) "
            "For UEM covers MDM/MAM/MCM/MEM/System groups; for others "
            "returns method, path, summary, parameters from the product's "
            "OpenAPI spec on developer.omnissa.com."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query about REST APIs (e.g. 'enroll device', 'GET profiles')",
                },
                "product": {
                    "type": "string",
                    "description": (
                        "Product slug. Default: 'uem'. One of: uem, horizon, "
                        "horizon_cloud, app_volumes, uag, access, intelligence, "
                        "identity_service."
                    ),
                    "default": "uem",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    ),
```

- [ ] **Step 2: Update the `call_tool` dispatch to pass `product`**

Find the `elif name == "search_api_reference":` branch. Replace its body with:

```python
        elif name == "search_api_reference":
            results = search_api(
                query=arguments["query"],
                db=_get_store("api"),
                product=arguments.get("product", "uem"),
                max_results=arguments.get("max_results", 10),
            )
```

- [ ] **Step 3: Sanity-check the server still imports**

```bash
python -c "from wingman_mcp.server import TOOLS; print(f'{len(TOOLS)} tools loaded')"
```

Expected: prints "(some number) tools loaded".

- [ ] **Step 4: Commit**

```bash
git add src/wingman_mcp/server.py
git commit -m "Add product param to search_api_reference tool"
```

---

## Task 8: Wire `<slug>_api` and `api` alias routing in `cli.py`

Plan 1 added `<slug>_rn` routing. This task mirrors that for API.

**Files:**
- Modify: `src/wingman_mcp/cli.py`

- [ ] **Step 1: Extend `cmd_ingest` vocabulary**

In `src/wingman_mcp/cli.py` `cmd_ingest`, find the `aliases` dict (added by Plan 1) and update it to include API targets:

```python
    aliases = {
        "all": (
            list(valid_keys)
            + [f"{s}_rn" for s in product_slugs]
            + [f"{s}_api" for s in product_slugs if PRODUCTS[s].api is not None]
        ),
        "docs": product_slugs,
        "rn": [f"{s}_rn" for s in product_slugs if PRODUCTS[s].release_notes is not None],
    }
```

(The `api` alias keyword resolves to the `api` combined-store key — already in `valid_keys` — so no separate alias entry is needed.)

In the target-classification loop, add a branch for `_api`:

```python
            elif k.endswith("_api"):
                slug = k[:-4]
                if slug not in product_slugs:
                    print(f"Error: unknown product in '{k}'.")
                    sys.exit(1)
                if PRODUCTS[slug].api is None and slug != "uem":
                    print(f"Error: {slug} has no REST API; '{k}' is not valid.")
                    sys.exit(1)
                api_targets.append(slug)
```

(Insert this `elif` *before* the existing `elif k in valid_keys:` branch.)

Add at the top of the function:

```python
    api_targets: list[str] = []
```

- [ ] **Step 2: Replace the API ingest phase**

Find the existing API ingest block in `cmd_ingest`:

```python
    if "api" in other_targets:
        print("\n--- Ingesting API reference (UEM only in this plan) ---")
        from wingman_mcp.ingest.ingest_api import ingest_api
        ingest_api(store_dir=get_store_dir("api"), embeddings=embeddings)
```

Replace with:

```python
    # If 'api' is in other_targets, expand it to all products with an api config + UEM.
    if "api" in other_targets:
        api_targets = ["uem"] + [s for s in product_slugs if PRODUCTS[s].api is not None]

    if api_targets:
        print(f"\n--- Ingesting API reference for: {', '.join(api_targets)} ---")
        from wingman_mcp.ingest.ingest_api import ingest_api, ingest_api_for_product
        for slug in api_targets:
            if slug == "uem":
                ingest_api(store_dir=get_store_dir("api"), embeddings=embeddings)
            else:
                ingest_api_for_product(
                    slug=slug,
                    store_dir=get_store_dir("api"),
                    embeddings=embeddings,
                )
```

- [ ] **Step 3: Mirror the change in `cmd_check`**

In `cmd_check`, update the `aliases` dict identically:

```python
    aliases = {
        "all": (
            list(valid_keys)
            + [f"{s}_rn" for s in product_slugs]
            + [f"{s}_api" for s in product_slugs if PRODUCTS[s].api is not None]
        ),
        "docs": product_slugs,
        "rn": [f"{s}_rn" for s in product_slugs if PRODUCTS[s].release_notes is not None],
    }
```

In the target-classification loop, add the `_api` branch (mirroring step 1):

```python
            elif k.endswith("_api"):
                slug = k[:-4]
                if slug not in product_slugs:
                    print(f"Error: unknown product in '{k}'.")
                    sys.exit(1)
                if PRODUCTS[slug].api is None and slug != "uem":
                    print(f"Error: {slug} has no REST API; '{k}' is not valid.")
                    sys.exit(1)
                targets.append(k)
```

- [ ] **Step 4: Update the `--list` output**

In `cmd_ingest` `--list`, the per-product axes section already mentions
`<slug>_api` (added by Plan 1). No change needed unless the wording is
stale — verify visually.

- [ ] **Step 5: Smoke-test rejection of invalid `*_api` targets**

```bash
wingman-mcp ingest dem_api 2>&1 | head -3
wingman-mcp ingest thinapp_api 2>&1 | head -3
```

Expected: each prints "Error: dem has no REST API; 'dem_api' is not valid." (or thinapp).

- [ ] **Step 6: Commit**

```bash
git add src/wingman_mcp/cli.py
git commit -m "Wire <slug>_api routing in ingest/check CLI; expand 'api' alias to all products"
```

---

## Task 9: Extend `check_api` to multi-product

**Files:**
- Modify: `src/wingman_mcp/ingest/check.py`

- [ ] **Step 1: Replace `check_api`**

In `src/wingman_mcp/ingest/check.py`, replace the existing `check_api` function with:

```python
def check_api(store_dir: str, products: Iterable[str] | None = None) -> dict:
    """Diff live API specs against what's stored, scoped to specific products."""
    print("\n=== Checking API reference store ===")
    if not Path(store_dir, "chroma.sqlite3").exists():
        print(f"  Store not found at {store_dir} — a full ingest is required.")
        return {"store": "api", "status": "missing"}

    if products is None:
        targets = ["uem"] + [s for s, c in PRODUCTS.items() if c.api is not None]
    else:
        targets = list(products)

    summary: dict[str, dict] = {}
    overall_changed = False

    if "uem" in targets:
        summary["uem"] = _check_uem_api(store_dir)
        targets.remove("uem")

    for slug in targets:
        cfg = PRODUCTS.get(slug)
        if cfg is None or cfg.api is None:
            continue
        summary[slug] = _check_product_api(slug, cfg, store_dir)

    for r in summary.values():
        v = r.get("verdict") or ""
        if v.startswith(("significant", "minor", "version")):
            overall_changed = True

    print("\n=== API summary ===")
    for slug, r in summary.items():
        print(f"  {slug:<18} {r.get('verdict', r.get('status', '?'))}")

    return {
        "store": "api",
        "per_product": summary,
        "verdict": (
            "rebuild recommended" if overall_changed else "no changes — rebuild not needed"
        ),
    }


def _check_uem_api(store_dir: str) -> dict:
    """Original UEM-only API check (preserved verbatim)."""
    live_sigs: dict[str, set[tuple[str, str]]] = {}
    for name, url in API_MAP.items():
        try:
            res = requests.get(url, timeout=20)
            if res.status_code != 200:
                live_sigs[name] = set()
                continue
            data = res.json()
            sigs = set()
            for path, methods in (data.get("paths") or {}).items():
                for method in methods.keys():
                    sigs.add((method.upper(), path))
            live_sigs[name] = sigs
        except Exception:
            live_sigs[name] = set()

    vs = _open_store(store_dir)
    stored_sigs: dict[str, set[tuple[str, str]]] = {}
    for m in _iter_metadatas(vs):
        if not m or m.get("product") != "uem":
            continue
        g = m.get("api_group")
        method = m.get("method")
        path = m.get("path")
        if g and method and path:
            stored_sigs.setdefault(g, set()).add((method, path))

    total_new = total_removed = total_live = 0
    print(f"  UEM groups:")
    for group in sorted(set(live_sigs) | set(stored_sigs)):
        live = live_sigs.get(group, set())
        stored = stored_sigs.get(group, set())
        new = len(live - stored)
        removed = len(stored - live)
        total_new += new
        total_removed += removed
        total_live += len(live)
        print(f"    {group:<15} live={len(live):>4} stored={len(stored):>4} +{new} -{removed}")

    changed_frac = (total_new + total_removed) / max(total_live, 1)
    verdict = _verdict(changed_frac, total_new, total_removed)
    print(f"  Verdict: {verdict}")
    return {"live": total_live, "new": total_new, "removed": total_removed, "verdict": verdict}


def _check_product_api(slug: str, cfg, store_dir: str) -> dict:
    """Diff a non-UEM product's live spec against its stored chunks."""
    from wingman_mcp.ingest.ingest_api import _fetch_spec
    print(f"  {slug} ({cfg.api.api_group})")

    if cfg.api.spec_format == "pdf":
        # Without re-downloading and re-extracting, we can only count stored chunks.
        vs = _open_store(store_dir)
        stored = sum(
            1 for m in _iter_metadatas(vs)
            if m and m.get("product") == slug and m.get("type") == "api_documentation"
        )
        verdict = "PDF — manual refresh recommended periodically"
        print(f"    stored chunks: {stored}; verdict: {verdict}")
        return {"stored": stored, "verdict": verdict}

    try:
        spec = _fetch_spec(cfg.api.spec_url, cfg.api.spec_format)
    except Exception as e:
        print(f"    fetch failed: {e}")
        return {"verdict": f"fetch failed: {e}"}

    live_sigs = set()
    for path, methods in (spec.get("paths") or {}).items():
        if isinstance(methods, dict):
            for method in methods.keys():
                if method.lower() in {
                    "get", "post", "put", "delete", "patch", "head", "options", "trace",
                }:
                    live_sigs.add((method.upper(), path))

    vs = _open_store(store_dir)
    stored_sigs = {
        (m.get("method"), m.get("path"))
        for m in _iter_metadatas(vs)
        if m and m.get("product") == slug and m.get("type") == "api_endpoint"
        and m.get("method") and m.get("path")
    }

    new = live_sigs - stored_sigs
    removed = stored_sigs - live_sigs
    print(f"    live={len(live_sigs)} stored={len(stored_sigs)} +{len(new)} -{len(removed)}")

    changed_frac = (len(new) + len(removed)) / max(len(live_sigs), 1)
    verdict = _verdict(changed_frac, len(new), len(removed))
    print(f"    verdict: {verdict}")
    return {
        "live": len(live_sigs),
        "stored": len(stored_sigs),
        "new": len(new),
        "removed": len(removed),
        "verdict": verdict,
    }
```

- [ ] **Step 2: Update `check_all` to forward API products**

In `check_all`, replace the existing `check_api` call with one that
forwards a per-product subset when `<slug>_api` targets are present:

```python
def check_all(targets: Iterable[str]) -> list[dict]:
    from wingman_mcp.config import get_store_dir

    targets = list(targets)
    rn_products, rn_combined = _split_rn_targets(targets)
    api_products = [t[:-4] for t in targets if t.endswith("_api")]
    api_combined = "api" in targets
    results = []

    if api_combined or api_products:
        api_target_products = None if api_combined else api_products
        results.append(check_api(get_store_dir("api"), products=api_target_products))

    for slug, product in PRODUCTS.items():
        if slug in targets:
            results.append(check_product(product, get_store_dir(slug)))

    if rn_combined or rn_products:
        rn_target_products = None if rn_combined else rn_products
        results.append(check_release_notes(
            get_store_dir("release_notes"),
            products=rn_target_products,
        ))

    print("\n=== Summary ===")
    for r in results:
        print(f"  {r.get('store'):<15} {r.get('verdict', r.get('status', '?'))}")
    return results
```

- [ ] **Step 3: Run all tests**

```bash
pytest -v
```

Expected: all green.

- [ ] **Step 4: Manual smoke check (network-dependent)**

```bash
wingman-mcp check api
```

Expected: per-product summary with `verdict` column for each product
that has an `api` config; UEM still uses `API_MAP`-based check.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/ingest/check.py
git commit -m "Make check_api per-product; preserve UEM API_MAP path"
```

---

## Task 10: Run the rollout & validate

**Files:** none (operational task)

- [ ] **Step 1: Build the API store across all products**

```bash
wingman-mcp ingest api
```

Expected: UEM ingests via `API_MAP`; the other 7 products fetch their
OpenAPI specs and add endpoint chunks to the same `api` store. Intelligence
fetches the PDF and adds prose chunks tagged `api_documentation`.

- [ ] **Step 2: Verify chunk distribution per product**

```bash
python -c "
from wingman_mcp.config import get_store_dir
from wingman_mcp.ingest.check import _open_store, _iter_metadatas
vs = _open_store(get_store_dir('api'))
by = {}
for m in _iter_metadatas(vs):
    if not m: continue
    key = (m.get('product', '?'), m.get('type', '?'))
    by[key] = by.get(key, 0) + 1
for (slug, t), n in sorted(by.items()):
    print(f'  {slug:<18} {t:<20} {n}')
"
```

Expected: rows for each product. UEM has `api_endpoint` rows; Intelligence has `api_documentation` rows; the rest have `api_endpoint` rows.

- [ ] **Step 3: Smoke-test multi-product API search**

```bash
python -c "
from langchain_chroma import Chroma
from wingman_mcp.embeddings import LocalEmbeddings
from wingman_mcp.config import get_store_dir
from wingman_mcp.search import search_api

db = Chroma(persist_directory=get_store_dir('api'), embedding_function=LocalEmbeddings())
for product, q in [
    ('horizon', 'create desktop pool'),
    ('app_volumes', 'list assignments'),
    ('uag', 'edge service'),
    ('access', 'list applications'),
    ('intelligence', 'authentication token'),
]:
    print(f'--- {product}: {q} ---')
    for r in search_api(q, db, product=product, max_results=2):
        print(' ', r['content'].splitlines()[0])
"
```

Expected: at least one result per product without error.

- [ ] **Step 4: Smoke-test `dem_api` rejection at search time**

```bash
python -c "
from langchain_chroma import Chroma
from wingman_mcp.embeddings import LocalEmbeddings
from wingman_mcp.config import get_store_dir
from wingman_mcp.search import search_api

db = Chroma(persist_directory=get_store_dir('api'), embedding_function=LocalEmbeddings())
results = search_api('foo', db, product='dem')
print(results[0]['content'])
"
```

Expected: prints the "DEM does not have a REST API" guidance message.

- [ ] **Step 5: Documentation refresh**

In `README.md`, update the API store row of the stores table to:

```markdown
| API references | `api` (or `<slug>_api`) | Multi-product REST APIs — UEM (live tenant Swagger), Horizon, Horizon Cloud, App Volumes, UAG, Access, Identity Service, Intelligence (PDF) |
```

```bash
git add README.md
git commit -m "Update README API row for multi-product coverage"
```

---

## Self-Review

Spec coverage check:

- API URLs for 7 products in scope → Task 3
- `ApiSource` dataclass → Task 2
- OpenAPI 2/3 walker (JSON + YAML) → Task 4
- PDF ingestion for Intelligence → Task 5
- `search_api_reference` gains `product` param → Tasks 6, 7
- DEM/ThinApp rejection → Task 6 (search-side); Task 8 (CLI-side)
- `check_api` extended → Task 9
- CLI vocabulary `<slug>_api` → Task 8
- Idempotent re-ingest per product → Task 4 (`ingest_api_for_product`) and Task 5 (`ingest_pdf_api`)
- Documentation refresh → Task 10 step 5

Type / signature consistency:

- `ApiSource(spec_url, api_group, spec_format, version)` — Task 2; consumed by Tasks 3, 4, 5, 8, 9.
- `_walk_openapi(spec, product, api_group, source_url, version)` — Task 4; not called outside that file.
- `ingest_api_for_product(slug, store_dir, embeddings)` — Task 4; called by `cmd_ingest` in Task 8.
- `ingest_pdf_api(product, vectorstore)` — Task 5; called by `ingest_api_for_product` (Task 4).
- `search_api(query, db, product="uem", max_results=10)` — Task 6; called by `server.py` in Task 7.
- `_lexical_api_fallback(db, query, product="uem", limit=8)` — Task 6.
- `check_api(store_dir, products=None)` — Task 9; called by `check_all` in Task 9 step 2.

Placeholder scan: none.

---

**Out-of-scope**:
- Auto-discovery of latest spec versions for Horizon/App Volumes — design notes the open question; deferred per spec.
- Changing UEM's live-tenant `API_MAP` model. UEM behavior is preserved unchanged.
