"""Ingest Omnissa product documentation into a Chroma store.

This is now product-driven: pass any ProductConfig from
`wingman_mcp.ingest.products` to crawl that product's docs into its own
Chroma store.  See `products.py` for the registry.

Backward compat: `ingest_docs()` still exists and ingests the UEM product
(matching the old behavior).
"""
import hashlib
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from tqdm import tqdm

from wingman_mcp.ingest.products import ProductConfig, get_product

USER_AGENT = "WingmanMCP/1.0"
DOCS_API_HOST = "https://docs-be.omnissa.com"
SITEMAP_LOC_RE = re.compile(r"<loc>(.*?)</loc>", re.IGNORECASE | re.DOTALL)
RN_VERSION_RE = re.compile(r"Release-NotesV(2\d{3})", re.IGNORECASE)

DEFAULT_SITEMAPS = [
    "https://docs.omnissa.com/sitemap.xml",
    "https://developer.omnissa.com/sitemap.xml",
    "https://techzone.omnissa.com/sitemap.xml",
]

# Skip versioned bundles unless they are release notes. Omnissa uses two
# formats for archive versions:
#   - V{yyyy}  e.g. V2209, V2410  (YYMM, no separator)
#   - V{yy}.{m} e.g. V25.11, V23.07, V22.1  (dot-separated)
# The unversioned / VSaaS variant is the current-version content.
_VERSIONED_BUNDLE_PATTERN = re.compile(
    r"V\d{4}(?!\w)|V\d{1,2}\.\d+",
    re.IGNORECASE,
)
_RELEASE_NOTES_BUNDLE_PATTERN = re.compile(
    r"(releasenotes|release-notes|-rn|_rn)", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Sitemap parsing
# ---------------------------------------------------------------------------

def _parse_sitemap(content):
    text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)
    return [m.strip() for m in SITEMAP_LOC_RE.findall(text) if m.strip()]


def _get_sub_sitemaps(url):
    """Return the list of sitemap files reachable from `url`.

    Two shapes are supported:
    * Sitemap-index (docs.omnissa.com): contains `<loc>` entries pointing
      to other sitemap.xml files. Returns those.
    * Flat urlset (techzone.omnissa.com): contains `<loc>` entries pointing
      directly to pages. Returns `[url]` so the caller re-fetches and
      treats its `<loc>` entries as page URLs.
    """
    try:
        res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    except requests.RequestException as e:
        print(f"  Warning: failed to fetch sitemap {url}: {e}")
        return []
    if res.status_code != 200:
        return []
    sub_xmls = [loc for loc in _parse_sitemap(res.content) if loc.lower().endswith(".xml")]
    if sub_xmls:
        return sub_xmls
    # Flat urlset — let the caller treat the input URL as a page-list sitemap.
    return [url]


def _extract_bundle(url):
    """Return the bundle name from a docs.omnissa.com URL, or None."""
    m = re.search(r"/bundle/([^/]+)/", url)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Per-product URL filter
# ---------------------------------------------------------------------------

def _make_should_ingest(product: ProductConfig):
    """Build a `_should_ingest(url)` callable for a given product config."""
    extra_bundle_set = {b.lower() for b in product.extra_bundles}
    include = list(product.include_keywords)
    exclude = list(product.exclude_keywords)
    skip_versioned = product.skip_versioned_bundles

    def _should(url: str) -> bool:
        low = url.lower()
        bundle = _extract_bundle(url)
        # Always include explicitly listed bundles
        if bundle and bundle.lower() in extra_bundle_set:
            return True
        # Skip versioned (archived) bundles unless they are release notes
        if (
            skip_versioned
            and bundle
            and _VERSIONED_BUNDLE_PATTERN.search(bundle)
            and not _RELEASE_NOTES_BUNDLE_PATTERN.search(bundle)
        ):
            return False
        return (
            any(k in low for k in include)
            and not any(k in low for k in exclude)
        )

    return _should


# ---------------------------------------------------------------------------
# Page download
# ---------------------------------------------------------------------------

def _build_docs_api_url(url):
    parsed = urlparse(url)
    if parsed.netloc.lower() != "docs.omnissa.com":
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 4 or parts[0] != "bundle" or parts[2] != "page":
        return None
    return f"{DOCS_API_HOST}/api/bundle/{parts[1]}/page/{'/'.join(parts[3:])}"


def _extract_text(url):
    api_url = _build_docs_api_url(url)
    if api_url:
        res = requests.get(api_url, timeout=15, headers={
            "User-Agent": USER_AGENT, "Accept-Language": "en-US",
        })
        if res.status_code == 200 and "application/json" in (res.headers.get("content-type") or ""):
            payload = res.json()
            html = (payload or {}).get("topic_html", "")
            if html:
                soup = BeautifulSoup(html, "html.parser")
                for s in soup(["script", "style"]):
                    s.decompose()
                text = soup.get_text(separator="\n", strip=True)
                title = payload.get("title")
                bundle_title = payload.get("bundle_title")
                desc = (payload.get("metadata") or {}).get("description")
                prefix = [p for p in [bundle_title, title, desc] if p]
                if prefix:
                    text = "\n\n".join(["\n".join(prefix), text])
                return {"text": text.strip(), "topic_payload": payload}

    # Plain-HTML fetch path (techzone, anything not on docs.omnissa.com).
    # 30s timeout — TechZone pages are large (~150 KB) and the CDN can be
    # slow under bursty parallel load.
    res = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
    if res.status_code != 200:
        return None
    soup = BeautifulSoup(res.content, "html.parser")
    for s in soup(["script", "style"]):
        s.decompose()
    return {"text": soup.get_text(separator=" ", strip=True), "topic_payload": None}


def _make_downloader(product: ProductConfig):
    """Build a `_download(url)` callable for a given product config."""
    use_inference = product.family_inference is not None
    allowed = product.allowed_families or set()
    fixed_family = product.slug

    def _download(url: str):
        try:
            extracted = _extract_text(url)
            if not extracted:
                return None
            tp = extracted.get("topic_payload")
            if use_inference:
                family = product.family_inference(url, tp)
                if family not in allowed:
                    return None
            else:
                family = fixed_family
            text = extracted["text"]
            meta = {"source": url, "product_family": family}
            tp = tp or {}
            if tp.get("title"):
                meta["title"] = tp["title"]
            if tp.get("bundle_title"):
                meta["bundle_title"] = tp["bundle_title"]
            version = RN_VERSION_RE.search(url or "")
            if version:
                meta.update({
                    "version": version.group(1),
                    "product": "Workspace ONE UEM",
                    "type": "release_notes",
                })
            return {
                "doc": Document(page_content=text, metadata=meta),
                "hash": hashlib.sha256(text.encode()).hexdigest(),
            }
        except Exception:
            return None

    return _download


def _fmt_duration(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ingest_product(
    product: ProductConfig,
    store_dir: str,
    embeddings,
    max_workers: int = 50,
    batch_size: int = 500,
):
    """Crawl Omnissa sitemaps and ingest one product's docs into store_dir."""
    t0 = time.time()
    print(f"\n[{product.slug}] {product.label}")
    print(f"  Store dir: {store_dir}")

    os.makedirs(store_dir, exist_ok=True)
    vectorstore = Chroma(persist_directory=store_dir, embedding_function=embeddings)
    splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)

    should_ingest = _make_should_ingest(product)
    download = _make_downloader(product)
    extra_bundle_set = {b.lower() for b in product.extra_bundles}

    # --- Phase 1: Discover URLs ---
    print(f"\n=== [{product.slug}] Phase 1/3: Discovering URLs from sitemaps ===")
    all_xmls = []
    for sitemap in DEFAULT_SITEMAPS:
        print(f"  Expanding: {sitemap}")
        all_xmls.extend(_get_sub_sitemaps(sitemap))
    print(f"  Found {len(all_xmls)} sub-sitemaps")

    def _fetch_and_filter_sitemap(xml_url):
        try:
            res = requests.get(xml_url, headers={"User-Agent": USER_AGENT}, timeout=30)
        except requests.RequestException:
            return []
        if res.status_code != 200:
            return []
        return [u for u in _parse_sitemap(res.content) if should_ingest(u)]

    all_urls = []
    bundles_found = set()
    sitemap_errors = 0
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_fetch_and_filter_sitemap, x): x for x in all_xmls}
        for future in tqdm(as_completed(futures), total=len(all_xmls), desc="  Parsing sitemaps"):
            try:
                results = future.result()
            except Exception:
                sitemap_errors += 1
                continue
            for u in results:
                all_urls.append(u)
                b = _extract_bundle(u)
                if b:
                    bundles_found.add(b)
    if sitemap_errors:
        print(f"  Warning: {sitemap_errors} sub-sitemap(s) failed to load; continuing with the rest.")

    all_urls = list(dict.fromkeys(all_urls))
    print(f"  {len(all_urls)} pages to ingest across {len(bundles_found)} bundles")

    if not all_urls:
        print(f"  No URLs matched the filter for product '{product.slug}'.")
        print(f"  Tip: refine include_keywords / extra_bundles in products.py.")
        return

    # --- Phase 2: Download & extract ---
    print(f"\n=== [{product.slug}] Phase 2/3: Downloading pages ({max_workers} workers) ===")
    all_docs = []
    # Every URL here already passed `should_ingest`, so a None return from
    # the downloader means the HTTP fetch or HTML extraction failed (timeout,
    # non-200, parse error, etc.) — not that we filtered it. Track these
    # separately from family-inference drops (where a doc downloaded fine but
    # got classified into a family the product doesn't accept).
    fetch_errors: list[str] = []
    family_drops = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download, u): u for u in all_urls}
        for future in tqdm(as_completed(futures), total=len(all_urls),
                           desc="  Fetching", unit="pg", smoothing=0.1):
            url = futures[future]
            result = future.result()
            if result is not None:
                all_docs.append(result["doc"])
            else:
                # Was this dropped by family inference (downloaded ok but
                # filtered post-fetch) or did the fetch itself fail?
                if product.family_inference is not None:
                    # Can't tell from here without a second probe. Conservative:
                    # call it a family drop if family inference is configured,
                    # else a fetch error.
                    family_drops += 1
                else:
                    fetch_errors.append(url)

    print(f"  Downloaded {len(all_docs)} pages "
          f"({len(fetch_errors)} fetch failures, {family_drops} family-filtered)")
    if fetch_errors:
        print(f"  Sample fetch failures (first 5):")
        for u in fetch_errors[:5]:
            print(f"    {u}")

    if not all_docs:
        print(f"  Nothing to embed for '{product.slug}'.")
        return

    # --- Phase 3: Chunk & embed ---
    print(f"\n=== [{product.slug}] Phase 3/3: Chunking & embedding ===")
    chunks = splitter.split_documents(all_docs)
    print(f"  {len(chunks)} chunks to embed")

    total_added = 0
    chroma_limit = 5000
    for j in tqdm(range(0, len(chunks), chroma_limit), desc="  Embedding", unit="batch"):
        batch = chunks[j: j + chroma_limit]
        vectorstore.add_documents(batch)
        total_added += len(batch)

    elapsed = time.time() - t0
    print(f"\n=== [{product.slug}] Done — {total_added} chunks added in {_fmt_duration(elapsed)} ===")


def ingest_docs(store_dir: str, embeddings, max_workers: int = 50, batch_size: int = 500):
    """Backward-compatible entry: ingest the UEM product."""
    ingest_product(get_product("uem"), store_dir, embeddings,
                   max_workers=max_workers, batch_size=batch_size)


# ---------------------------------------------------------------------------
# Compatibility re-exports for code that imported helpers from this module
# (notably check.py).  Build them from the UEM product config.
# ---------------------------------------------------------------------------

_UEM = get_product("uem")
INCLUDE_KEYWORDS = _UEM.include_keywords
EXCLUDE_KEYWORDS = _UEM.exclude_keywords
ALLOWED_FAMILIES = _UEM.allowed_families or set()
EXTRA_BUNDLES = _UEM.extra_bundles
_should_ingest = _make_should_ingest(_UEM)
_infer_family = _UEM.family_inference
_download = _make_downloader(_UEM)
