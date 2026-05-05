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
    """Return True if `bundle` belongs to this product's release notes.

    Matching is case-insensitive — Omnissa bundle names are inconsistent
    on capitalisation (e.g. ``horizon-client-windows-RN`` vs the lowercase
    siblings on other platforms).
    """
    if not bundle:
        return False
    lower = bundle.lower()
    if lower in {b.lower() for b in rn.bundle_exact}:
        return True
    return any(lower.startswith(p.lower()) for p in rn.bundle_prefixes)


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
    assert rn is not None and (rn.bundle_prefixes or rn.bundle_exact), (
        f"_discover_rn_urls_for requires bundle_prefixes or bundle_exact on {product.slug}"
    )

    all_xmls: list[str] = []
    for sm in DEFAULT_SITEMAPS:
        all_xmls.extend(_get_sub_sitemaps(sm))

    def _fetch(xml_url):
        try:
            r = requests.get(xml_url, headers={"User-Agent": USER_AGENT}, timeout=30)
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
    assert rn is not None and (rn.bundle_prefixes or rn.bundle_exact), (
        f"_ingest_docs_web requires bundle_prefixes or bundle_exact on {product.slug}"
    )

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
        rn = cfg.release_notes
        # Run docs_web first if bundle prefixes/exacts are configured.
        # Then run uem_txt second so that — for any version where a local
        # .txt file is present — its sectioned chunks overwrite the
        # docs_web chunks for that (product, version) pair.
        if rn.bundle_prefixes or rn.bundle_exact:
            _ingest_docs_web(cfg, vectorstore, splitter)
        if rn.source_type == "uem_txt":
            _ingest_uem_txt(cfg, vectorstore, splitter, content_hashes)

    if content_hashes:
        hash_file.write_text(
            "\n".join(f"{k}={v}" for k, v in sorted(content_hashes.items())) + "\n"
        )
