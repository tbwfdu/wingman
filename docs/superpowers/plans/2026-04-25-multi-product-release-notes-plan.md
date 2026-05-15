# Multi-product Release Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make release notes a first-class, per-product searchable axis for all Omnissa products in the wingman-mcp registry, replacing the UEM-only RN pipeline with a registry-driven multi-product ingester.

**Architecture:** One combined `release_notes` Chroma store, with `product` metadata as the search-time filter. Each `ProductConfig` gains an optional `ReleaseNotesSource` describing how to find that product's RN bundles. UEM keeps its local-`.txt` workflow (`source_type="uem_txt"`); non-UEM products scrape RN bundles from `docs.omnissa.com` (`source_type="docs_web"`) using the same `_extract_text` helper that powers the docs ingest. `search_release_notes` gains an optional `product` parameter (defaults to `"uem"` for backward compat) and a version-normalization step so that `"2412"` and `"24.12"` match the same Access bundle.

**Tech Stack:** Python 3.10+, langchain-chroma, requests, BeautifulSoup, pytest (added by this plan).

**Spec:** `docs/superpowers/specs/2026-04-25-multi-product-rag-ingest-design.md`

---

## File Map

**Create:**
- `tests/__init__.py` — empty marker
- `tests/conftest.py` — shared fixtures (none yet, but reserves the path)
- `tests/test_version_expansion.py` — table-driven `_expand_version` tests
- `tests/test_products_release_notes_config.py` — assertions on the registry shape
- `tests/test_release_notes_ingest_helpers.py` — version regex, DEM normalization, hash-file migration
- `tests/test_check_release_notes.py` — multi-product check helper

**Modify:**
- `pyproject.toml` — add `[dev]` extras (pytest), add `[tool.pytest.ini_options]`
- `src/wingman_mcp/ingest/products.py` — add `ReleaseNotesSource`, add field on `ProductConfig`, narrow `_UEM_ALLOWED_FAMILIES`, attach RN config to all 7 existing products, add 3 new products (`access`, `intelligence`, `identity_service`)
- `src/wingman_mcp/ingest/ingest_release_notes.py` — full rewrite: registry-driven, two source types
- `src/wingman_mcp/ingest/check.py` — extend `check_release_notes` to per-product
- `src/wingman_mcp/search.py` — add `_expand_version`, extend `search_release_notes` with `product` arg + version expansion
- `src/wingman_mcp/server.py` — update tool description + inputSchema for `search_release_notes`
- `src/wingman_mcp/cli.py` — vocabulary expansion: `<slug>_rn`, `rn` alias; updated `--list` output
- `README.md` — refresh stores section
- `INGEST_MACOS.md` — note non-UEM products are scraped from docs.omnissa.com

---

## Task 1: Set up pytest infrastructure

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Add `[dev]` extras and pytest config to `pyproject.toml`**

In the `[project.optional-dependencies]` block, add a `dev` group. Append a `[tool.pytest.ini_options]` block at the end of the file.

```toml
[project.optional-dependencies]
# ...existing groups...
dev = [
    "pytest>=8.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-q"
```

- [ ] **Step 2: Create `tests/__init__.py`**

```python
```

(Empty file — just marks the directory as a package so pytest discovery is unambiguous.)

- [ ] **Step 3: Create `tests/conftest.py`**

```python
"""Shared pytest fixtures for wingman-mcp tests."""
```

- [ ] **Step 4: Install dev extras and run pytest sanity-check**

```bash
pip install -e '.[dev,ingest]'
pytest -q
```

Expected: "no tests ran in 0.0s" (no errors).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/__init__.py tests/conftest.py
git commit -m "Add pytest dev extras and empty tests skeleton"
```

---

## Task 2: Add `ReleaseNotesSource` dataclass and `release_notes` field on `ProductConfig`

**Files:**
- Modify: `src/wingman_mcp/ingest/products.py`
- Create: `tests/test_products_release_notes_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_products_release_notes_config.py`:

```python
"""Smoke tests on the PRODUCTS registry shape."""
from wingman_mcp.ingest.products import (
    PRODUCTS,
    ProductConfig,
    ReleaseNotesSource,
)


def test_release_notes_source_defaults():
    rn = ReleaseNotesSource(bundle_prefixes=["Foo"])
    assert rn.bundle_prefixes == ["Foo"]
    assert rn.bundle_exact == []
    assert rn.source_type == "docs_web"
    assert rn.version_re == r"V(\d{4}(?:\.\d+)?)"
    assert rn.section_splitter is None


def test_product_config_accepts_release_notes():
    cfg = ProductConfig(
        slug="foo",
        label="Foo",
        description="",
        release_notes=ReleaseNotesSource(bundle_prefixes=["FooRN"]),
    )
    assert cfg.release_notes is not None
    assert cfg.release_notes.bundle_prefixes == ["FooRN"]


def test_product_config_release_notes_default_none():
    cfg = ProductConfig(slug="foo", label="Foo", description="")
    assert cfg.release_notes is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_products_release_notes_config.py -v
```

Expected: ImportError on `ReleaseNotesSource` (or AttributeError on `ProductConfig.release_notes`).

- [ ] **Step 3: Add `ReleaseNotesSource` dataclass and field**

In `src/wingman_mcp/ingest/products.py`, near the top (after `from typing import Callable, Optional`), add:

```python
from typing import Callable, Literal, Optional
```

Then, just above the existing `@dataclass class ProductConfig:` block, insert:

```python
@dataclass
class ReleaseNotesSource:
    """How to discover and parse a product's release notes."""
    bundle_prefixes: list[str] = field(default_factory=list)
    bundle_exact:    list[str] = field(default_factory=list)
    source_type:     Literal["docs_web", "uem_txt"] = "docs_web"
    # Regex applied to a bundle name to extract the version string.
    # Default matches "V2603", "V25.11", "V2506.1", etc.
    version_re:      str = r"V(\d{4}(?:\.\d+)?)"
    # Optional callable: text -> [(section_name, section_text), ...]
    section_splitter: Optional[Callable[[str], list[tuple[str, str]]]] = None
```

In the existing `ProductConfig` dataclass, add a new field at the end (after `search_prefix: str = ""`):

```python
    release_notes: Optional[ReleaseNotesSource] = None
```

- [ ] **Step 4: Re-run the test to verify it passes**

```bash
pytest tests/test_products_release_notes_config.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/ingest/products.py tests/test_products_release_notes_config.py
git commit -m "Add ReleaseNotesSource dataclass and ProductConfig.release_notes field"
```

---

## Task 3: Wire up `release_notes` config for existing products (UEM, Horizon, Horizon Cloud, App Volumes, UAG, DEM, ThinApp)

**Files:**
- Modify: `src/wingman_mcp/ingest/products.py`
- Modify: `tests/test_products_release_notes_config.py`

- [ ] **Step 1: Extend the test with assertions for each existing product**

Append to `tests/test_products_release_notes_config.py`:

```python
import pytest


_EXISTING_SLUGS_WITH_RN = [
    "uem",
    "horizon",
    "horizon_cloud",
    "app_volumes",
    "uag",
    "dem",
    "thinapp",
]


@pytest.mark.parametrize("slug", _EXISTING_SLUGS_WITH_RN)
def test_existing_product_has_release_notes(slug):
    cfg = PRODUCTS[slug]
    assert cfg.release_notes is not None, f"{slug} is missing release_notes config"


def test_uem_uses_txt_source():
    cfg = PRODUCTS["uem"]
    assert cfg.release_notes.source_type == "uem_txt"
    assert cfg.release_notes.section_splitter is not None


def test_dem_version_re_strips_underscores():
    """DEM bundle names look like Dynamic-Environment-Manager_2111.1_..."""
    import re
    cfg = PRODUCTS["dem"]
    m = re.search(cfg.release_notes.version_re, "Dynamic-Environment-Manager_2111.1_AdminGuide")
    assert m is not None
    assert m.group(1) == "2111.1"


def test_app_volumes_rn_bundle_prefixes():
    cfg = PRODUCTS["app_volumes"]
    assert any(p.startswith("AppVolumesReleaseNotes") for p in cfg.release_notes.bundle_prefixes)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_products_release_notes_config.py -v
```

Expected: 7 of the new tests fail (release_notes is None on all existing products).

- [ ] **Step 3: Extract the UEM section splitter into a reusable helper**

In `src/wingman_mcp/ingest/products.py`, add this helper near the top of the file (after the imports, before `_NEVER_INGEST`):

```python
# ---------------------------------------------------------------------------
# UEM release-notes section splitter (extracted from legacy ingest_release_notes.py
# so it can be carried as a ProductConfig field).
# ---------------------------------------------------------------------------

import re as _re_rn

_UEM_SECTION_HEADING_RE = _re_rn.compile(
    r"^[A-Za-z ]+ "
    r"(Management|Experience|Orchestrator|Architecture|Enrollment|Platform)$"
)


def _uem_split_by_sections(text: str) -> list[tuple[str, str]]:
    """Split UEM release-notes text into (section_name, body) tuples."""
    sections: list[tuple[str, str]] = []
    current_section = "General"
    current_content: list[str] = []
    for line in text.split("\n"):
        if _UEM_SECTION_HEADING_RE.match(line.strip()):
            if current_content:
                sections.append((current_section, "\n".join(current_content)))
            current_section = line.strip()
            current_content = []
        else:
            current_content.append(line)
    if current_content:
        sections.append((current_section, "\n".join(current_content)))
    return sections
```

- [ ] **Step 4: Attach a `release_notes` config to each of the 7 existing products**

Inside each existing `ProductConfig(...)` literal in `PRODUCTS`, add a `release_notes=...` argument. Specifically:

For `"uem"`, add:

```python
        release_notes=ReleaseNotesSource(
            source_type="uem_txt",
            version_re=r"v(\d{4})",
            section_splitter=_uem_split_by_sections,
        ),
```

For `"horizon"`, add:

```python
        release_notes=ReleaseNotesSource(
            bundle_prefixes=["Horizon-Release-Notes", "HorizonReleaseNotes"],
        ),
```

For `"horizon_cloud"`, add:

```python
        release_notes=ReleaseNotesSource(
            bundle_exact=["HorizonCloudService-next-gen-ReleaseNotes"],
            version_re=r"$nope^",  # never matches → version defaults to "rolling"
        ),
```

For `"app_volumes"`, add:

```python
        release_notes=ReleaseNotesSource(
            bundle_prefixes=["AppVolumesReleaseNotes"],
        ),
```

For `"uag"`, add:

```python
        release_notes=ReleaseNotesSource(
            bundle_prefixes=["UnifiedAccessGatewayReleaseNotes"],
        ),
```

For `"dem"`, add:

```python
        release_notes=ReleaseNotesSource(
            bundle_prefixes=["Dynamic-Environment-Manager"],
            # DEM uses underscore-delimited versions in bundle names.
            version_re=r"_(\d{4}(?:\.\d+)?)_",
        ),
```

For `"thinapp"`, add:

```python
        release_notes=ReleaseNotesSource(
            bundle_prefixes=["ThinAppReleaseNotes"],
        ),
```

- [ ] **Step 5: Re-run the tests**

```bash
pytest tests/test_products_release_notes_config.py -v
```

Expected: all tests pass (10+ tests including the 3 from Task 2).

- [ ] **Step 6: Commit**

```bash
git add src/wingman_mcp/ingest/products.py tests/test_products_release_notes_config.py
git commit -m "Wire release_notes config for existing 7 products"
```

---

## Task 4: Add 3 new products to the registry — `access`, `intelligence`, `identity_service`

**Files:**
- Modify: `src/wingman_mcp/ingest/products.py`
- Modify: `tests/test_products_release_notes_config.py`

- [ ] **Step 1: Extend the test for the new products**

Append to `tests/test_products_release_notes_config.py`:

```python
_NEW_SLUGS = ["access", "intelligence", "identity_service"]


@pytest.mark.parametrize("slug", _NEW_SLUGS)
def test_new_product_registered(slug):
    assert slug in PRODUCTS, f"{slug} missing from PRODUCTS"


@pytest.mark.parametrize("slug", _NEW_SLUGS)
def test_new_product_has_docs_config(slug):
    cfg = PRODUCTS[slug]
    assert cfg.include_keywords, f"{slug} has no include_keywords for docs ingest"


@pytest.mark.parametrize("slug", _NEW_SLUGS)
def test_new_product_has_release_notes(slug):
    cfg = PRODUCTS[slug]
    assert cfg.release_notes is not None
    # All three are rolling/single-bundle RN.
    assert cfg.release_notes.bundle_exact, (
        f"{slug} should pin RN bundles via bundle_exact (single canonical bundle)"
    )


def test_total_product_count():
    assert len(PRODUCTS) == 10
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_products_release_notes_config.py -v
```

Expected: tests for `access`, `intelligence`, `identity_service` fail (KeyError on PRODUCTS lookup); `test_total_product_count` fails (currently 7).

- [ ] **Step 3: Add the three new products to the `PRODUCTS` dict**

Append the following entries inside `PRODUCTS` (after the existing `dem` entry):

```python
    # -----------------------------------------------------------------------
    # Workspace ONE Access (split out of the UEM ecosystem store)
    # -----------------------------------------------------------------------
    "access": ProductConfig(
        slug="access",
        label="Workspace ONE Access",
        description="Omnissa Workspace ONE Access (formerly Identity Manager).",
        include_keywords=[
            "workspace-one-access", "workspaceoneaccess", "ws1-access",
            "ws1_access", "AccessABM", "AccessEdgeDeviceSignals",
            "AccessPlatformSSO", "WorkspaceONEAccessDesktopClient",
        ],
        exclude_keywords=[
            "horizon-cloud", "app-volumes", "thinapp", "horizon-html-access",
            "unified-access-gateway", "accessgateway", "access-gateway",
            *_NEVER_INGEST,
        ],
        skip_versioned_bundles=True,
        search_prefix="Omnissa Workspace ONE Access",
        release_notes=ReleaseNotesSource(
            bundle_exact=[
                "workspace-one-access-release-notes",
                "workspace-one-access-release-notes-fedramp",
            ],
            bundle_prefixes=["workspace-one-access-release-notes"],
            # Access uses dotted yy.mm: V24.12, V23.09, etc.
            version_re=r"V?(\d{2}\.\d{2}(?:\.\d+\.\d+)?)",
        ),
    ),

    # -----------------------------------------------------------------------
    # Workspace ONE Intelligence (split out of the UEM ecosystem store)
    # -----------------------------------------------------------------------
    "intelligence": ProductConfig(
        slug="intelligence",
        label="Workspace ONE Intelligence",
        description="Omnissa Workspace ONE Intelligence — analytics & automation.",
        include_keywords=["intelligence"],
        exclude_keywords=[
            "horizon", "app-volumes", "thinapp", "uem", "access",
            *_NEVER_INGEST,
        ],
        extra_bundles=["Intelligence"],
        skip_versioned_bundles=True,
        search_prefix="Omnissa Workspace ONE Intelligence",
        release_notes=ReleaseNotesSource(
            bundle_exact=["IntelligenceRN"],
            version_re=r"$nope^",  # never matches → "rolling"
        ),
    ),

    # -----------------------------------------------------------------------
    # Omnissa Identity Service (new — no prior store)
    # -----------------------------------------------------------------------
    "identity_service": ProductConfig(
        slug="identity_service",
        label="Omnissa Identity Service",
        description="Omnissa Identity Service — cloud identity / authentication.",
        include_keywords=["identityservice", "identity-service"],
        exclude_keywords=[
            "horizon", "app-volumes", "thinapp", "uem", "access",
            "intelligence",
            *_NEVER_INGEST,
        ],
        extra_bundles=["IdentityServices", "IdentityServiceMigration"],
        skip_versioned_bundles=True,
        search_prefix="Omnissa Identity Service",
        release_notes=ReleaseNotesSource(
            bundle_exact=["identity-services-release-notes"],
            version_re=r"$nope^",  # rolling
        ),
    ),
```

- [ ] **Step 4: Re-run the tests**

```bash
pytest tests/test_products_release_notes_config.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/ingest/products.py tests/test_products_release_notes_config.py
git commit -m "Add access, intelligence, identity_service to PRODUCTS registry"
```

---

## Task 5: Narrow `_UEM_ALLOWED_FAMILIES` to `{"uem", "hub"}`

This is the core "split-out" change for Section 1 of the spec. After this commit, re-running `wingman-mcp ingest uem` will rebuild the UEM store without Access or Intelligence content.

**Files:**
- Modify: `src/wingman_mcp/ingest/products.py`
- Modify: `tests/test_products_release_notes_config.py`

- [ ] **Step 1: Add a test asserting the new family allowlist**

Append to `tests/test_products_release_notes_config.py`:

```python
def test_uem_family_allowlist_excludes_access_and_intelligence():
    cfg = PRODUCTS["uem"]
    assert cfg.allowed_families == {"uem", "hub"}, (
        "Access and Intelligence should no longer be merged into the UEM store"
    )


def test_uem_family_inference_still_classifies_access_pages():
    """Inference should still recognise an Access page; the change is that
    those pages now get filtered OUT at download time because 'access' is
    no longer in allowed_families."""
    cfg = PRODUCTS["uem"]
    family = cfg.family_inference(
        "https://docs.omnissa.com/bundle/workspace-one-access-administration-guideVSaaS/page/x.html",
        None,
    )
    assert family == "access"
    assert family not in cfg.allowed_families
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_products_release_notes_config.py::test_uem_family_allowlist_excludes_access_and_intelligence -v
```

Expected: AssertionError — current allowlist still contains `access` and `intelligence`.

- [ ] **Step 3: Narrow `_UEM_ALLOWED_FAMILIES`**

In `src/wingman_mcp/ingest/products.py`, find:

```python
_UEM_ALLOWED_FAMILIES = {"uem", "access", "hub", "intelligence"}
```

Replace with:

```python
_UEM_ALLOWED_FAMILIES = {"uem", "hub"}
```

- [ ] **Step 4: Update the UEM `exclude_keywords` to skip Access and Intelligence URLs at sitemap-filter time**

This is a defense-in-depth tweak: family inference filters at download time, but adding URL-level excludes prevents pointless fetches. Find the UEM `exclude_keywords` list (currently includes `"vdi", "app-volumes", ...`) and append:

```python
            "workspace-one-access", "workspaceoneaccess", "ws1-access",
            "ws1_access", "intelligence",
```

(Add inside the existing list, before `*_NEVER_INGEST`.)

- [ ] **Step 5: Re-run all tests**

```bash
pytest -v
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/wingman_mcp/ingest/products.py tests/test_products_release_notes_config.py
git commit -m "Narrow UEM family allowlist to {uem, hub}; Access and Intelligence split out"
```

---

## Task 6: Add `_expand_version` helper to `search.py`

**Files:**
- Modify: `src/wingman_mcp/search.py`
- Create: `tests/test_version_expansion.py`

- [ ] **Step 1: Write the failing test (table-driven)**

Create `tests/test_version_expansion.py`:

```python
"""Table-driven tests for version normalization."""
import pytest

from wingman_mcp.search import _expand_version


@pytest.mark.parametrize("user_input,expected_subset", [
    # 4-digit yymm → adds dotted yy.mm form
    ("2412", {"2412", "24.12"}),
    ("24.12", {"2412", "24.12"}),
    ("2603", {"2603", "26.03"}),
    # Patch suffix
    ("2506.1", {"2506.1", "25061"}),
    # Leading 'v' is stripped
    ("v2602", {"2602", "26.02"}),
    ("V24.12", {"2412", "24.12"}),
    # Whitespace tolerated
    ("  2412  ", {"2412", "24.12"}),
])
def test_expand_version_table(user_input, expected_subset):
    result = set(_expand_version(user_input))
    assert expected_subset.issubset(result), (
        f"For input {user_input!r}, expected {expected_subset} ⊆ result, got {result}"
    )


def test_expand_version_returns_sorted_list():
    result = _expand_version("2412")
    assert isinstance(result, list)
    assert result == sorted(result)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_version_expansion.py -v
```

Expected: ImportError — `_expand_version` not defined.

- [ ] **Step 3: Add the helper to `src/wingman_mcp/search.py`**

Near the top of `src/wingman_mcp/search.py` (right after the existing `_keyword_tokens` helper), add:

```python
def _expand_version(v: str) -> List[str]:
    """Expand a user-supplied version into all equivalent stored forms.

    Different products store versions in different forms (Access uses
    "24.12"; UEM/Horizon use "2412"-style). Users typically don't know
    which form. This expands the input into a candidate set that covers
    both, suitable for a Chroma `$in` filter.
    """
    v = (v or "").lower().lstrip("v").strip()
    candidates = {v, v.replace(".", "")}
    # 4-digit yymm input → add the dotted yy.mm form.
    if re.fullmatch(r"\d{4}", v):
        candidates.add(f"{v[:2]}.{v[2:]}")
    # 5-6 digit input like '250601' → add yy.mm.patch form.
    if re.fullmatch(r"\d{5,6}", v):
        candidates.add(f"{v[:2]}.{v[2:4]}.{v[4:]}")
    return sorted(candidates)
```

- [ ] **Step 4: Re-run the test**

```bash
pytest tests/test_version_expansion.py -v
```

Expected: all parametrized cases pass.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/search.py tests/test_version_expansion.py
git commit -m "Add _expand_version helper for product-aware version filtering"
```

---

## Task 7: Extend `search_release_notes` to accept `product` parameter

**Files:**
- Modify: `src/wingman_mcp/search.py`

- [ ] **Step 1: Replace the body of `search_release_notes`**

Find the existing `search_release_notes` function in `src/wingman_mcp/search.py` (currently at the bottom of the file; iterates `COMPONENT_LABELS` for UEM). Replace the entire function with:

```python
def search_release_notes(
    query: str,
    db: Chroma,
    version: Optional[str] = None,
    product: str = "uem",
    max_results: int = 15,
) -> List[Dict[str, str]]:
    """Search the combined release-notes store, scoped to one product.

    Defaults to product='uem' so existing callers keep working unchanged.
    Component-focused multi-pass search (Windows / macOS / etc.) only fires
    for UEM, since those headings are UEM-specific.
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
    search_prefix = cfg.search_prefix or cfg.label
    docs: List[Any] = []

    # Build version filter (with normalization expansion).
    version_clause = None
    if version:
        version_clause = {"version": {"$in": _expand_version(version)}}

    base_filter: Dict[str, Any] = {
        "$and": [
            {"product": product},
            {"type": "release_notes"},
        ],
    }
    if version_clause:
        base_filter["$and"].append(version_clause)

    # Primary search.
    docs.extend(db.similarity_search(query, k=max_results * 2, filter=base_filter))

    # UEM-only: component-focused multi-pass (preserves existing behaviour).
    if product == "uem" and version:
        for label in COMPONENT_LABELS.values():
            focus_query = f"{search_prefix} {label} updates release notes"
            docs.extend(db.similarity_search(focus_query, k=5, filter=base_filter))

    filtered = [d for d in docs if not _is_boilerplate(d)]
    deduped = _dedup(filtered)

    # Score: prefer matching version, then recency.
    expanded_versions = set(_expand_version(version)) if version else set()

    def score(doc):
        meta = getattr(doc, "metadata", {}) or {}
        s = 0
        v = meta.get("version", "")
        if version and v in expanded_versions:
            s += 50
        # Numeric-version recency boost (only meaningful for yymm-style).
        if v and v != "rolling":
            try:
                s += int(v.replace(".", ""))
            except ValueError:
                pass
        return s

    deduped.sort(key=score, reverse=True)
    return _format_results(deduped[:max_results])
```

(The existing `COMPONENT_LABELS` dict above the function is preserved unchanged.)

- [ ] **Step 2: Run all tests to confirm no regression in pure helpers**

```bash
pytest -v
```

Expected: all green.

- [ ] **Step 3: Smoke-test against a built RN store (skip if none exists yet)**

If `~/.wingman-mcp/stores/release_notes/chroma.sqlite3` exists, run:

```bash
python -c "
from langchain_chroma import Chroma
from wingman_mcp.embeddings import LocalEmbeddings
from wingman_mcp.config import get_store_dir
from wingman_mcp.search import search_release_notes

db = Chroma(persist_directory=get_store_dir('release_notes'), embedding_function=LocalEmbeddings())
results = search_release_notes('what is new', db, product='uem', max_results=3)
for r in results:
    print(r['source'], '-', r['content'][:80])
"
```

Expected: 3 UEM RN results print without error. (If the store doesn't exist yet, skip; we'll exercise this once Task 9 fills the store.)

- [ ] **Step 4: Commit**

```bash
git add src/wingman_mcp/search.py
git commit -m "Extend search_release_notes with product filter and version normalization"
```

---

## Task 8: Update `server.py` tool description and inputSchema

**Files:**
- Modify: `src/wingman_mcp/server.py`

- [ ] **Step 1: Update the `search_release_notes` Tool definition**

In `src/wingman_mcp/server.py`, find the `Tool(name="search_release_notes", ...)` block. Replace its `description` and `inputSchema` with:

```python
    Tool(
        name="search_release_notes",
        description=(
            "Search Omnissa product release notes for feature changes, "
            "bug fixes, resolved issues, and new capabilities. "
            "Supports product filter (default: 'uem'). Valid products: "
            "uem, horizon, horizon_cloud, app_volumes, uag, dem, thinapp, "
            "access, intelligence, identity_service. "
            "Supports version filter where applicable (e.g. UEM '2602', "
            "Horizon '2603', Access '24.12'). Version input is normalized: "
            "'2412' and '24.12' match the same Access bundle."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query about release notes or version changes",
                },
                "product": {
                    "type": "string",
                    "description": (
                        "Product slug. Default: 'uem'. One of: uem, horizon, "
                        "horizon_cloud, app_volumes, uag, dem, thinapp, access, "
                        "intelligence, identity_service."
                    ),
                    "default": "uem",
                },
                "version": {
                    "type": "string",
                    "description": (
                        "Optional version filter. Examples: UEM '2602', Horizon "
                        "'2603', Access '24.12' (or '2412' — both match)."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default: 15)",
                    "default": 15,
                },
            },
            "required": ["query"],
        },
    ),
```

- [ ] **Step 2: Update the `call_tool` dispatch to pass `product`**

Find the `elif name == "search_release_notes":` branch in the `call_tool` async function. Replace its body with:

```python
        elif name == "search_release_notes":
            results = search_release_notes(
                query=arguments["query"],
                db=_get_store("release_notes"),
                version=arguments.get("version"),
                product=arguments.get("product", "uem"),
                max_results=arguments.get("max_results", 15),
            )
```

- [ ] **Step 3: Update the `search_omnissa_docs` Tool description to list the 3 new product slugs**

Find the existing `Tool(name="search_omnissa_docs", ...)` block. In its `description`, replace the slug list with:

```
"Product slug. One of: uem, horizon, horizon_cloud, app_volumes, uag, "
"thinapp, dem, access, intelligence, identity_service."
```

(This is the only change for `search_omnissa_docs` — the dispatch logic is already product-agnostic.)

- [ ] **Step 4: Sanity-check the server still imports**

```bash
python -c "from wingman_mcp.server import TOOLS; print(f'{len(TOOLS)} tools loaded')"
```

Expected: prints "(some number) tools loaded" with no traceback.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/server.py
git commit -m "Add product param to search_release_notes tool; update tool descriptions"
```

---

## Task 9: Rewrite `ingest_release_notes.py` — `docs_web` source path

**Files:**
- Modify: `src/wingman_mcp/ingest/ingest_release_notes.py`
- Create: `tests/test_release_notes_ingest_helpers.py`

- [ ] **Step 1: Write tests for the pure helpers we're about to add**

Create `tests/test_release_notes_ingest_helpers.py`:

```python
"""Tests for the pure helpers in the new ingest_release_notes module."""
import pytest

from wingman_mcp.ingest.ingest_release_notes import (
    _bundle_matches,
    _extract_version,
    _migrate_hash_keys,
)
from wingman_mcp.ingest.products import PRODUCTS


def test_bundle_matches_prefix():
    rn = PRODUCTS["app_volumes"].release_notes
    assert _bundle_matches("AppVolumesReleaseNotesV2603", rn)
    assert _bundle_matches("AppVolumesReleaseNotesV2512", rn)
    assert not _bundle_matches("AppVolumesAdminGuideV2603", rn)


def test_bundle_matches_exact():
    rn = PRODUCTS["intelligence"].release_notes
    assert _bundle_matches("IntelligenceRN", rn)
    assert not _bundle_matches("Intelligence", rn)


def test_extract_version_yymm():
    rn = PRODUCTS["horizon"].release_notes
    assert _extract_version("Horizon-Release-Notes-V2603", rn) == "2603"


def test_extract_version_dem_strips_underscores():
    rn = PRODUCTS["dem"].release_notes
    assert (
        _extract_version("Dynamic-Environment-Manager_2111.1_AdminGuide", rn)
        == "2111.1"
    )


def test_extract_version_access_dotted():
    rn = PRODUCTS["access"].release_notes
    assert _extract_version("workspace-one-access-release-notesV24.12", rn) == "24.12"


def test_extract_version_rolling_when_no_match():
    rn = PRODUCTS["intelligence"].release_notes
    assert _extract_version("IntelligenceRN", rn) == "rolling"


def test_migrate_hash_keys_legacy_uem():
    """Legacy hash entries with bare version keys get prefixed with uem:."""
    legacy = {"2506": "abc", "2509": "def", "uem:2602": "ghi"}
    migrated = _migrate_hash_keys(legacy)
    assert migrated == {
        "uem:2506": "abc",
        "uem:2509": "def",
        "uem:2602": "ghi",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_release_notes_ingest_helpers.py -v
```

Expected: ImportError.

- [ ] **Step 3: Replace `src/wingman_mcp/ingest/ingest_release_notes.py` with the rewrite**

Overwrite the file completely with:

```python
"""Multi-product release-notes ingestion.

Each ProductConfig may declare a ReleaseNotesSource describing how to
discover and parse that product's release notes. Two source types are
supported:

* ``docs_web`` — sitemap-driven scrape of docs.omnissa.com bundles
* ``uem_txt`` — UEM-specific local v{version}_rn.txt workflow

Output goes into one combined Chroma store (the ``release_notes`` store)
with ``product`` metadata as the primary search-time filter.
"""
from __future__ import annotations

import hashlib
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from wingman_mcp.ingest.ingest_docs import (
    DEFAULT_SITEMAPS,
    USER_AGENT,
    _extract_bundle,
    _extract_text,
    _get_sub_sitemaps,
    _parse_sitemap,
)
from wingman_mcp.ingest.products import (
    PRODUCTS,
    ProductConfig,
    ReleaseNotesSource,
)

# UEM-only legacy version map (preserved for backward compat).
VERSION_MAP = {
    "2506": "https://docs.omnissa.com/bundle/Workspace-ONE-UEM-Release-NotesV2506/page/WorkspaceONEUEM-ReleaseNotes.html",
    "2509": "https://docs.omnissa.com/bundle/Workspace-ONE-UEM-Release-NotesV2509/page/WorkspaceONEUEM-ReleaseNotes.html",
    "2602": "https://docs.omnissa.com/bundle/Workspace-ONE-UEM-Release-NotesV2602/page/WorkspaceONEUEM-ReleaseNotes.html",
}

_SEARCH_DIRS = [
    Path.cwd(),
    Path.cwd().parent / "files",
    Path.cwd().parent / "archive" / "backups",
]


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------

def _bundle_matches(bundle: str, rn: ReleaseNotesSource) -> bool:
    """Return True if `bundle` belongs to this product's release notes."""
    if bundle in rn.bundle_exact:
        return True
    return any(bundle.startswith(p) for p in rn.bundle_prefixes)


def _extract_version(bundle: str, rn: ReleaseNotesSource) -> str:
    """Extract a version string from a bundle name; return 'rolling' if no match."""
    m = re.search(rn.version_re, bundle or "")
    return m.group(1) if m else "rolling"


def _migrate_hash_keys(legacy: dict[str, str]) -> dict[str, str]:
    """Migrate legacy `<version>=<sha>` entries to `uem:<version>=<sha>`.

    Already-prefixed keys (containing ':') are passed through unchanged.
    """
    out: dict[str, str] = {}
    for k, v in legacy.items():
        out[k if ":" in k else f"uem:{k}"] = v
    return out


def _find_rn_file(version: str) -> Path | None:
    filename = f"v{version}_rn.txt"
    for d in _SEARCH_DIRS:
        candidate = d / filename
        if candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# docs_web ingest path
# ---------------------------------------------------------------------------

def _discover_rn_urls_for(product: ProductConfig) -> list[str]:
    """Walk the docs.omnissa.com sitemaps and return URLs for this product's RN."""
    import requests

    rn = product.release_notes
    assert rn is not None and rn.source_type == "docs_web"

    all_xmls: list[str] = []
    for sm in DEFAULT_SITEMAPS:
        all_xmls.extend(_get_sub_sitemaps(sm))

    def _fetch(xml_url):
        try:
            r = requests.get(xml_url, headers={"User-Agent": USER_AGENT}, timeout=15)
            if r.status_code != 200:
                return []
            return _parse_sitemap(r.content)
        except Exception:
            return []

    rn_urls: set[str] = set()
    with ThreadPoolExecutor(max_workers=20) as ex:
        for urls in ex.map(_fetch, all_xmls):
            for u in urls:
                bundle = _extract_bundle(u)
                if bundle and _bundle_matches(bundle, rn):
                    rn_urls.add(u)
    return sorted(rn_urls)


def _ingest_docs_web(
    product: ProductConfig,
    vectorstore: Chroma,
    splitter: RecursiveCharacterTextSplitter,
) -> int:
    rn = product.release_notes
    assert rn is not None and rn.source_type == "docs_web"

    print(f"  Discovering RN bundles for {product.slug}...")
    urls = _discover_rn_urls_for(product)
    if not urls:
        print(f"  No RN bundles found for {product.slug}. Check bundle_prefixes/bundle_exact.")
        return 0
    print(f"  {len(urls)} RN page(s) to ingest")

    # Group URLs by version, so we can scope the idempotent delete per (product,version).
    by_version: dict[str, list[str]] = {}
    for u in urls:
        bundle = _extract_bundle(u) or ""
        v = _extract_version(bundle, rn)
        by_version.setdefault(v, []).append(u)

    total_chunks = 0
    for version, version_urls in by_version.items():
        # Idempotent: drop existing chunks for (product, version) before adding.
        try:
            existing = vectorstore.get(where={"$and": [
                {"product": product.slug},
                {"version": version},
            ]})
            existing_ids = existing.get("ids", [])
            if existing_ids:
                vectorstore.delete(ids=existing_ids)
        except Exception as e:
            print(f"  ({product.slug} {version}) cleanup skipped: {e}")

        docs: list[Document] = []
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(_extract_text, u): u for u in version_urls}
            for fut in as_completed(futures):
                url = futures[fut]
                try:
                    extracted = fut.result()
                except Exception:
                    extracted = None
                if not extracted:
                    continue
                text = extracted["text"]
                tp = extracted.get("topic_payload") or {}
                bundle = _extract_bundle(url) or ""
                title = tp.get("title") or ""
                bundle_title = tp.get("bundle_title") or ""
                header_lines = [bundle_title, title, f"Version: {version}"]
                header = "\n".join([h for h in header_lines if h])
                for chunk in splitter.split_text(text):
                    docs.append(Document(
                        page_content=f"{header}\n\n{chunk}" if header else chunk,
                        metadata={
                            "product": product.slug,
                            "product_label": product.label,
                            "version": version,
                            "bundle": bundle,
                            "source": url,
                            "type": "release_notes",
                        },
                    ))

        if docs:
            vectorstore.add_documents(docs)
            total_chunks += len(docs)
            print(f"  {product.slug} v{version}: {len(docs)} chunks")
    return total_chunks


# ---------------------------------------------------------------------------
# uem_txt ingest path (preserves legacy behaviour)
# ---------------------------------------------------------------------------

def _ingest_uem_txt(
    product: ProductConfig,
    vectorstore: Chroma,
    splitter: RecursiveCharacterTextSplitter,
    content_hashes: dict[str, str],
) -> int:
    rn = product.release_notes
    assert rn is not None and rn.source_type == "uem_txt"
    section_splitter = rn.section_splitter
    assert section_splitter is not None, "uem_txt requires a section_splitter"

    total = 0
    for version, url in VERSION_MAP.items():
        txt_file = _find_rn_file(version)
        if txt_file is None:
            print(f"  Skip uem v{version}: v{version}_rn.txt not found")
            continue

        # Idempotent: clear existing UEM chunks for this version.
        existing = vectorstore.get(where={"$and": [
            {"product": "uem"},
            {"version": version},
        ]})
        existing_ids = existing.get("ids", [])
        if existing_ids:
            vectorstore.delete(ids=existing_ids)

        text = txt_file.read_text(encoding="utf-8")
        content_hashes[f"uem:{version}"] = hashlib.sha256(text.encode()).hexdigest()
        sections = section_splitter(text)
        docs: list[Document] = []
        for sec_name, sec_text in sections:
            header = f"Workspace ONE UEM Version {version} - {sec_name}\n\n"
            for chunk in splitter.split_text(sec_text):
                docs.append(Document(
                    page_content=header + chunk,
                    metadata={
                        "product": "uem",
                        "product_label": product.label,
                        "version": version,
                        "bundle": f"uem-txt:v{version}",
                        "source": url,
                        "section": sec_name,
                        "type": "release_notes",
                    },
                ))
        if docs:
            vectorstore.add_documents(docs)
            total += len(docs)
            print(f"  uem v{version}: {len(docs)} chunks")
    return total


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_release_notes(
    store_dir: str,
    embeddings,
    products: Iterable[str] | None = None,
):
    """Ingest release notes for one or more products into the combined RN store.

    Parameters
    ----------
    store_dir : str
        Directory of the combined release_notes Chroma store.
    embeddings : Embeddings
        Embedding function used by the Chroma collection.
    products : iterable of slug strings, optional
        Restrict ingestion to these products. Defaults to all products that
        have a `release_notes` config.
    """
    os.makedirs(store_dir, exist_ok=True)
    vectorstore = Chroma(persist_directory=store_dir, embedding_function=embeddings)
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)

    # Load + migrate the hash file.
    hash_file = Path(store_dir) / ".content-hashes.txt"
    content_hashes: dict[str, str] = {}
    if hash_file.exists():
        for line in hash_file.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                content_hashes[k.strip()] = v.strip()
        content_hashes = _migrate_hash_keys(content_hashes)

    targets = list(products) if products else [
        slug for slug, cfg in PRODUCTS.items() if cfg.release_notes is not None
    ]

    for slug in targets:
        cfg = PRODUCTS.get(slug)
        if cfg is None or cfg.release_notes is None:
            print(f"  Skip {slug}: no release_notes config")
            continue
        print(f"\n=== Ingesting release notes for {slug} ({cfg.label}) ===")
        if cfg.release_notes.source_type == "uem_txt":
            _ingest_uem_txt(cfg, vectorstore, splitter, content_hashes)
        else:
            _ingest_docs_web(cfg, vectorstore, splitter)

    if content_hashes:
        hash_file.write_text(
            "\n".join(f"{k}={v}" for k, v in sorted(content_hashes.items())) + "\n"
        )
```

- [ ] **Step 4: Re-run all tests**

```bash
pytest -v
```

Expected: all green (helpers in `test_release_notes_ingest_helpers.py` plus everything from earlier tasks).

- [ ] **Step 5: Verify the legacy UEM-only entry point still imports cleanly**

The signature changed (`store_dir, embeddings, products=None`). Confirm it still callable as before:

```bash
python -c "
from wingman_mcp.ingest.ingest_release_notes import ingest_release_notes
import inspect
sig = inspect.signature(ingest_release_notes)
assert 'products' in sig.parameters
print('OK')
"
```

Expected: prints "OK".

- [ ] **Step 6: Commit**

```bash
git add src/wingman_mcp/ingest/ingest_release_notes.py tests/test_release_notes_ingest_helpers.py
git commit -m "Rewrite ingest_release_notes as registry-driven multi-product ingester"
```

---

## Task 10: Update `cli.py` — `<slug>_rn` and `rn` alias routing

**Files:**
- Modify: `src/wingman_mcp/cli.py`

- [ ] **Step 1: Replace the body of `cmd_ingest`**

Find `def cmd_ingest(args):` in `src/wingman_mcp/cli.py`. Replace the whole function with:

```python
def cmd_ingest(args):
    """Run ingestion scripts to build stores."""
    try:
        from wingman_mcp.embeddings import LocalEmbeddings
    except ImportError:
        print("The ingest command is not available in this distribution.")
        sys.exit(1)

    from wingman_mcp.config import get_store_dir, get_store_keys
    from wingman_mcp.ingest.products import PRODUCTS, list_product_slugs

    if getattr(args, "list", False):
        print("Available stores:\n")
        print("  Product documentation:")
        for slug in list_product_slugs():
            cfg = PRODUCTS[slug]
            print(f"    {slug:<18} {cfg.label}")
        print("\n  Combined stores:")
        print(f"    {'api':<18} REST API references — supports all products with APIs")
        print(f"    {'release_notes':<18} Release notes — supports all products")
        print("\n  Per-product axes (writes to combined stores):")
        print(f"    {'<slug>_rn':<18} e.g. horizon_rn — that product's release notes only")
        print(f"    {'<slug>_api':<18} e.g. horizon_api — that product's API spec only")
        print(f"    {' ':<18} (DEM and ThinApp have no API and reject *_api targets)")
        print("\n  Aliases:")
        print(f"    {'docs':<18} every product's documentation")
        print(f"    {'rn':<18} every product's release notes")
        print(f"    {'all':<18} everything (default when no targets given)")
        return

    product_slugs = list_product_slugs()
    valid_keys = set(get_store_keys())
    aliases = {
        "all": list(valid_keys) + [f"{s}_rn" for s in product_slugs],
        "docs": product_slugs,
        "rn": [f"{s}_rn" for s in product_slugs if PRODUCTS[s].release_notes is not None],
    }

    raw_targets = args.stores or ["all"]
    docs_targets: list[str] = []
    rn_targets: list[str] = []
    other_targets: list[str] = []
    seen: set[str] = set()

    for t in raw_targets:
        expanded = aliases.get(t, [t])
        for k in expanded:
            if k in seen:
                continue
            seen.add(k)
            if k.endswith("_rn"):
                slug = k[:-3]
                if slug not in product_slugs:
                    print(f"Error: unknown product in '{k}'.")
                    sys.exit(1)
                rn_targets.append(slug)
            elif k in valid_keys:
                if k in product_slugs:
                    docs_targets.append(k)
                else:
                    other_targets.append(k)
            else:
                print(f"Error: unknown store '{k}'. Run 'wingman-mcp ingest --list' for options.")
                sys.exit(1)

    embeddings = LocalEmbeddings()

    # Phase 1: per-product docs ingest
    for slug in product_slugs:
        if slug in docs_targets:
            print(f"\n--- Ingesting {slug} documentation ---")
            from wingman_mcp.ingest.ingest_docs import ingest_product
            ingest_product(
                product=PRODUCTS[slug],
                store_dir=get_store_dir(slug),
                embeddings=embeddings,
                max_workers=args.max_workers,
                batch_size=args.batch_size,
            )

    # Phase 2: API reference (single combined store)
    if "api" in other_targets:
        print("\n--- Ingesting API reference (UEM only in this plan) ---")
        from wingman_mcp.ingest.ingest_api import ingest_api
        ingest_api(store_dir=get_store_dir("api"), embeddings=embeddings)

    # Phase 3: release notes (combined store, per-product targets)
    if "release_notes" in other_targets:
        rn_targets = [s for s in product_slugs if PRODUCTS[s].release_notes is not None]
    if rn_targets:
        print(f"\n--- Ingesting release notes for: {', '.join(rn_targets)} ---")
        from wingman_mcp.ingest.ingest_release_notes import ingest_release_notes
        ingest_release_notes(
            store_dir=get_store_dir("release_notes"),
            embeddings=embeddings,
            products=rn_targets,
        )

    print("\nIngestion complete.")
```

- [ ] **Step 2: Replace the body of `cmd_check` to mirror the same vocabulary**

Find `def cmd_check(args):` and replace with:

```python
def cmd_check(args):
    """Report what would change if stores were rebuilt."""
    try:
        from wingman_mcp.ingest.check import check_all
    except ImportError:
        print("The check command is not available in this distribution "
              "(ingest extras not installed). Run: pip install -e '.[ingest]'")
        sys.exit(1)

    from wingman_mcp.config import get_store_keys
    from wingman_mcp.ingest.products import PRODUCTS, list_product_slugs

    product_slugs = list_product_slugs()
    valid_keys = set(get_store_keys())
    aliases = {
        "all": list(valid_keys) + [f"{s}_rn" for s in product_slugs],
        "docs": product_slugs,
        "rn": [f"{s}_rn" for s in product_slugs if PRODUCTS[s].release_notes is not None],
    }

    raw_targets = args.stores or ["all"]
    targets: list[str] = []
    seen: set[str] = set()
    for t in raw_targets:
        expanded = aliases.get(t, [t])
        for k in expanded:
            if k in seen:
                continue
            seen.add(k)
            if k.endswith("_rn"):
                slug = k[:-3]
                if slug not in product_slugs:
                    print(f"Error: unknown product in '{k}'.")
                    sys.exit(1)
                targets.append(k)
            elif k in valid_keys:
                targets.append(k)
            else:
                print(f"Error: unknown store '{k}'.")
                sys.exit(1)
    check_all(targets)
```

- [ ] **Step 3: Manual smoke test of `--list`**

```bash
wingman-mcp ingest --list
```

Expected: prints the new layout (product table + combined stores + per-product axes + aliases).

- [ ] **Step 4: Manual smoke test of synthetic targets**

```bash
wingman-mcp ingest --list >/dev/null   # baseline check
wingman-mcp ingest doesnotexist  || echo "Got expected error"
```

Expected: 'unknown store' error message.

- [ ] **Step 5: Commit**

```bash
git add src/wingman_mcp/cli.py
git commit -m "Add <slug>_rn and rn alias routing to ingest/check CLI"
```

---

## Task 11: Extend `check_release_notes` to multi-product

**Files:**
- Modify: `src/wingman_mcp/ingest/check.py`
- Create: `tests/test_check_release_notes.py`

- [ ] **Step 1: Write a focused test for the per-product slicing logic**

Create `tests/test_check_release_notes.py`:

```python
"""Tests for the per-product slicing in check_release_notes."""
from wingman_mcp.ingest.check import _split_rn_targets


def test_split_rn_targets_handles_combined_alias():
    products, combined = _split_rn_targets(["release_notes"])
    assert combined is True
    # When the combined target is present, products list is irrelevant
    # — check_release_notes will iterate everything.


def test_split_rn_targets_extracts_per_product_axes():
    products, combined = _split_rn_targets(["horizon_rn", "uag_rn"])
    assert combined is False
    assert products == ["horizon", "uag"]


def test_split_rn_targets_passes_through_unrelated():
    products, combined = _split_rn_targets(["uem", "api"])
    assert combined is False
    assert products == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_check_release_notes.py -v
```

Expected: ImportError on `_split_rn_targets`.

- [ ] **Step 3: Add `_split_rn_targets` and refactor `check_release_notes`**

In `src/wingman_mcp/ingest/check.py`, add this helper near the top (after the existing `_open_store`):

```python
def _split_rn_targets(targets: Iterable[str]) -> tuple[list[str], bool]:
    """Pull RN-specific targets out of a mixed target list.

    Returns (per_product_slugs, has_combined_target). If has_combined_target
    is True, callers should ingest/check ALL products' RN.
    """
    targets = list(targets)
    combined = "release_notes" in targets
    products: list[str] = []
    for t in targets:
        if t.endswith("_rn"):
            products.append(t[:-3])
    return products, combined
```

Then replace the entire `check_release_notes` function with the multi-product version:

```python
def check_release_notes(store_dir: str, products: Iterable[str] | None = None) -> dict:
    """Report RN-store drift, optionally scoped to specific products.

    For UEM, retains the local-`.txt` content-hash check.
    For other products, diffs sitemap-discoverable RN bundles against
    bundle names already in the store.
    """
    print("\n=== Checking release notes store ===")
    if not Path(store_dir, "chroma.sqlite3").exists():
        print(f"  Store not found at {store_dir} — a full ingest is required.")
        return {"store": "release_notes", "status": "missing"}

    vs = _open_store(store_dir)

    # Build the set of products to check.
    if products is None:
        targets = [s for s, c in PRODUCTS.items() if c.release_notes is not None]
    else:
        targets = [s for s in products if s in PRODUCTS and PRODUCTS[s].release_notes]

    summary: dict[str, dict] = {}
    overall_changed = False

    for slug in targets:
        cfg = PRODUCTS[slug]
        rn = cfg.release_notes
        print(f"\n--- {slug} ({cfg.label}) ---")
        if rn.source_type == "uem_txt":
            summary[slug] = _check_uem_txt_rn(slug, store_dir, vs)
        else:
            summary[slug] = _check_docs_web_rn(slug, cfg, vs)
        if summary[slug].get("verdict", "").startswith(
            ("significant", "minor", "version", "content")
        ):
            overall_changed = True

    print("\n=== Release-notes summary ===")
    for slug, r in summary.items():
        print(f"  {slug:<18} {r.get('verdict', r.get('status', '?'))}")

    return {
        "store": "release_notes",
        "per_product": summary,
        "verdict": (
            "rebuild recommended" if overall_changed else "no changes — rebuild not needed"
        ),
    }


def _check_uem_txt_rn(slug: str, store_dir: str, vs) -> dict:
    """Per-product UEM .txt content-hash check (legacy behaviour)."""
    stored_versions = {
        m.get("version") for m in _iter_metadatas(vs)
        if m and m.get("product") == slug and m.get("version")
    }
    configured = set(VERSION_MAP.keys())
    new_versions = configured - stored_versions
    removed_versions = stored_versions - configured

    print(f"  Configured versions: {sorted(configured)}")
    print(f"  Versions in store:   {sorted(stored_versions)}")

    hash_file = Path(store_dir) / ".content-hashes.txt"
    prior_hashes: dict[str, str] = {}
    if hash_file.exists():
        for line in hash_file.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                prior_hashes[k.strip()] = v.strip()

    changed = 0
    for version in sorted(configured):
        path = _find_rn_file(version)
        if path is None:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        h = hashlib.sha256(text.encode()).hexdigest()
        prior = prior_hashes.get(f"uem:{version}", prior_hashes.get(version))
        if prior is None:
            continue
        if prior != h:
            changed += 1

    if new_versions or removed_versions:
        verdict = "version set changed — rebuild recommended"
    elif changed:
        verdict = f"{changed} version(s) have updated content — rebuild recommended"
    else:
        verdict = "no changes — rebuild not needed"
    print(f"  Verdict: {verdict}")
    return {
        "configured_versions": sorted(configured),
        "stored_versions": sorted(stored_versions),
        "content_changed": changed,
        "verdict": verdict,
    }


def _check_docs_web_rn(slug: str, cfg, vs) -> dict:
    """Diff sitemap-discoverable RN bundles vs what's in the store for this product."""
    from wingman_mcp.ingest.ingest_release_notes import _discover_rn_urls_for, _bundle_matches

    live_urls = set(_discover_rn_urls_for(cfg))
    stored_urls = {
        m.get("source") for m in _iter_metadatas(vs)
        if m and m.get("product") == slug and m.get("source")
    }
    new = live_urls - stored_urls
    removed = stored_urls - live_urls

    print(f"  Live RN URLs:    {len(live_urls)}")
    print(f"  Stored RN URLs:  {len(stored_urls)}")
    print(f"  New:    {len(new)}")
    print(f"  Removed: {len(removed)}")

    baseline = max(len(live_urls), len(stored_urls), 1)
    changed_frac = (len(new) + len(removed)) / baseline
    verdict = _verdict(changed_frac, len(new), len(removed))
    print(f"  Verdict: {verdict}")
    return {
        "live": len(live_urls),
        "stored": len(stored_urls),
        "new": len(new),
        "removed": len(removed),
        "verdict": verdict,
    }
```

Add the missing import at the top of `check.py`:

```python
import hashlib
```

(Replace the existing `import hashlib` if it's not already at module top — it is in the current file. Skip if already present.)

- [ ] **Step 4: Update the top-level `check_all` driver**

In `check_all`, replace the existing per-target dispatch with vocabulary-aware routing:

```python
def check_all(targets: Iterable[str]) -> list[dict]:
    from wingman_mcp.config import get_store_dir

    targets = list(targets)
    rn_products, rn_combined = _split_rn_targets(targets)
    results = []

    if "api" in targets:
        results.append(check_api(get_store_dir("api")))

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

- [ ] **Step 5: Re-run all tests**

```bash
pytest -v
```

Expected: all green.

- [ ] **Step 6: Manual smoke check (no network if no store exists)**

```bash
wingman-mcp check release_notes
```

If no RN store exists yet: prints "Store not found ... full ingest required". If a store exists: prints per-product summaries.

- [ ] **Step 7: Commit**

```bash
git add src/wingman_mcp/ingest/check.py tests/test_check_release_notes.py
git commit -m "Make check_release_notes per-product; add _split_rn_targets vocab helper"
```

---

## Task 12: Update documentation (README, INGEST_MACOS)

**Files:**
- Modify: `README.md`
- Modify: `INGEST_MACOS.md`

- [ ] **Step 1: Refresh the README "Stores" section**

Open `README.md` and find the section listing stores (look for "stores", "ingest", or "RAG store"). Replace the product table with:

```markdown
### Stores

Each Omnissa product has its own documentation store; release notes and
API references live in two combined stores keyed by `product` metadata.

| Store | Slug(s) | What's in it |
|---|---|---|
| Workspace ONE UEM docs | `uem` | UEM admin guides, configuration, profiles, Hub |
| Horizon docs | `horizon` | Horizon 8 / Enterprise on-prem VDI |
| Horizon Cloud docs | `horizon_cloud` | Horizon Cloud Service / DaaS |
| App Volumes docs | `app_volumes` | App Volumes admin & deployment |
| UAG docs | `uag` | Unified Access Gateway |
| DEM docs | `dem` | Dynamic Environment Manager |
| ThinApp docs | `thinapp` | ThinApp packaging |
| Access docs | `access` | Workspace ONE Access (split out of UEM) |
| Intelligence docs | `intelligence` | Workspace ONE Intelligence (split out of UEM) |
| Identity Service docs | `identity_service` | Omnissa Identity Service |
| Release notes | `release_notes` (or `<slug>_rn`) | All products' release notes, filterable |
| API references | `api` (or `<slug>_api`) | UEM REST API; non-UEM products coming in Plan 2 |

Build all of them with `wingman-mcp ingest`. Build only one product's
release notes with e.g. `wingman-mcp ingest horizon_rn`.
```

- [ ] **Step 2: Add a note in `INGEST_MACOS.md`**

At the top of `INGEST_MACOS.md`, add a new short section:

```markdown
## Per-product release notes

The `v{version}_rn.txt` workflow described below is **UEM-only**. Release
notes for all other products (Horizon, App Volumes, UAG, DEM, ThinApp,
Access, Intelligence, Identity Service) are scraped automatically from
`docs.omnissa.com` — no local files needed.

To rebuild just one product's release notes:

    wingman-mcp ingest horizon_rn

To rebuild all products' release notes:

    wingman-mcp ingest rn
```

- [ ] **Step 3: Commit**

```bash
git add README.md INGEST_MACOS.md
git commit -m "Document multi-product release-notes ingest in README and INGEST_MACOS"
```

---

## Task 13: Run the full migration sequence and validate

This is the rollout step. It moves the live wingman-mcp data dir to the
new layout. If you'd rather rehearse it on a throwaway data dir first,
set `WINGMAN_MCP_DATA_DIR=/tmp/wmcp-test` for the duration.

**Files:** none (operational task)

- [ ] **Step 1: Rebuild the UEM store with the narrower family allowlist**

```bash
wingman-mcp ingest uem
```

Expected: completes in ~10–20 minutes. Output should show fewer pages
than before (Access and Intelligence pages are now excluded by the
sitemap-level URL filter and the family allowlist).

- [ ] **Step 2: Build the three new docs stores**

```bash
wingman-mcp ingest access intelligence identity_service
```

Expected: each one ingests its respective bundles into a brand-new store.

- [ ] **Step 3: Build the combined release-notes store**

```bash
wingman-mcp ingest rn
```

Expected: walks all 10 products' RN configurations. UEM uses local
`.txt` files (skipped if not present, with a "Skip uem v{version}"
message); the other 9 scrape from docs.omnissa.com.

- [ ] **Step 4: Verify the UEM store no longer contains Access or Intelligence pages**

```bash
python -c "
from wingman_mcp.config import get_store_dir
from wingman_mcp.ingest.check import _open_store, _iter_metadatas
vs = _open_store(get_store_dir('uem'))
families = {m.get('product_family') for m in _iter_metadatas(vs) if m}
print('Families in UEM store:', sorted(f for f in families if f))
assert 'access' not in families, 'access should be split out'
assert 'intelligence' not in families, 'intelligence should be split out'
print('Migration verified: access and intelligence are no longer in the UEM store.')
"
```

Expected: prints something like `['general', 'hub', 'uem']` and the assertion message.

- [ ] **Step 5: Verify the combined RN store has chunks per product**

```bash
python -c "
from wingman_mcp.config import get_store_dir
from wingman_mcp.ingest.check import _open_store, _iter_metadatas
vs = _open_store(get_store_dir('release_notes'))
by_product: dict[str, int] = {}
for m in _iter_metadatas(vs):
    if m and m.get('type') == 'release_notes':
        by_product[m.get('product', '?')] = by_product.get(m.get('product', '?'), 0) + 1
for slug, n in sorted(by_product.items()):
    print(f'  {slug:<18} {n} chunks')
"
```

Expected: a row for each product that has a `release_notes` config; chunk
counts > 0 for each (UEM may be 0 if no `.txt` files are local).

- [ ] **Step 6: Smoke-test the search tool**

```bash
python -c "
from langchain_chroma import Chroma
from wingman_mcp.embeddings import LocalEmbeddings
from wingman_mcp.config import get_store_dir
from wingman_mcp.search import search_release_notes

db = Chroma(persist_directory=get_store_dir('release_notes'), embedding_function=LocalEmbeddings())
for product in ['horizon', 'app_volumes', 'access']:
    print(f'--- {product} ---')
    results = search_release_notes('what is new', db, product=product, max_results=2)
    for r in results:
        print(' ', r['source'][:80])
"
```

Expected: each product returns at least one result with a docs.omnissa.com source URL.

- [ ] **Step 7: Final commit (only if anything changed in this task)**

This task is operational; no code changes typically. If the migration
exposed a bug fixed in a follow-up tweak, commit that here.

---

## Self-Review

Spec coverage check (each spec section → task):

- Final product registry (10 products) → Tasks 3, 4
- Storage & data model (combined RN store, metadata schema, idempotency, hash file) → Tasks 9, 10
- Ingestion pipeline 3a (RN, multi-product) → Task 9
- Ingestion 3b (API) → out of scope; **Plan 2**
- Ingestion 3c (PDF API) → out of scope; **Plan 2**
- Ingestion 3e (RN content also in docs stores) → no work needed; existing `ingest_docs.py` already preserves RN bundles
- Search-tool surface → Tasks 7, 8 (RN side); API side **Plan 2**
- Version normalization → Task 6
- CLI / `<slug>_rn` / `rn` alias → Task 10
- `check` command → Task 11
- Migration plan → Task 13
- Documentation updates → Task 12
- Testing approach (`_expand_version`, version_re, idempotency) → Tasks 6, 9; idempotency exercised by re-running ingest in Task 13

Type / signature consistency:

- `ReleaseNotesSource` defined in Task 2; referenced consistently in Tasks 3, 4, 9, 11.
- `_extract_version` and `_bundle_matches` defined in Task 9 helpers; consumed by Task 11.
- `search_release_notes(query, db, version=None, product="uem", max_results=15)` — signature matches between Tasks 7 (impl) and 8 (server wiring).
- `ingest_release_notes(store_dir, embeddings, products=None)` — signature matches between Task 9 (impl) and Task 10 (CLI caller).

Placeholder scan: none.

---

**Out-of-scope reminders for Plan 2:**
- API ingestion across the 7 products that have an API
- `search_api_reference` gains `product` parameter
- `check_api` extension across products
- New `ingest_api_pdf.py` for Intelligence
