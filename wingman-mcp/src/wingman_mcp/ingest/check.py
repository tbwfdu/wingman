"""Report what would change if stores were rebuilt — without modifying anything.

Compares the current upstream state of each source against what's already in
the Chroma stores, so you can decide whether a refresh is worthwhile.
"""
from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import requests

from wingman_mcp.ingest.ingest_docs import (
    DEFAULT_SITEMAPS,
    USER_AGENT,
    _extract_bundle,
    _get_sub_sitemaps,
    _parse_sitemap,
    _should_ingest,
)
from wingman_mcp.ingest.ingest_api import API_MAP, _sanitize_url
from wingman_mcp.ingest.ingest_release_notes import (
    VERSION_MAP,
    _find_rn_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_store(store_dir: str):
    """Open an existing Chroma store read-only (no embedding function needed
    for pure metadata/count queries)."""
    from langchain_chroma import Chroma

    # We only read metadata — a dummy embedding function is fine.
    class _NullEmbeddings:
        def embed_documents(self, texts): return [[0.0] for _ in texts]
        def embed_query(self, text): return [0.0]

    return Chroma(persist_directory=store_dir, embedding_function=_NullEmbeddings())


def _iter_metadatas(vectorstore, page_size: int = 2000):
    """Yield metadatas in pages (Chroma's SQLite backend chokes on single
    get() calls for large collections — SQL variable limit)."""
    offset = 0
    while True:
        data = vectorstore.get(include=["metadatas"], limit=page_size, offset=offset)
        metas = data.get("metadatas") or []
        if not metas:
            return
        for m in metas:
            yield m
        if len(metas) < page_size:
            return
        offset += len(metas)


def _distinct_sources(vectorstore) -> set[str]:
    return {m.get("source") for m in _iter_metadatas(vectorstore) if m and m.get("source")}


def _fmt(n: int) -> str:
    return f"{n:,}"


def _verdict(changed_frac: float, new_count: int, removed_count: int) -> str:
    """Decide whether a rebuild looks worthwhile."""
    if new_count == 0 and removed_count == 0:
        return "no changes — rebuild not needed"
    if changed_frac >= 0.05 or (new_count + removed_count) >= 50:
        return "significant changes — rebuild recommended"
    if changed_frac >= 0.01 or (new_count + removed_count) >= 10:
        return "minor changes — rebuild optional"
    return "trivial changes — rebuild not urgent"


# ---------------------------------------------------------------------------
# UEM docs
# ---------------------------------------------------------------------------

def check_uem(store_dir: str) -> dict:
    """Diff Omnissa sitemap URLs against what's in the uem Chroma store."""
    print("\n=== Checking UEM docs store ===")
    if not Path(store_dir, "chroma.sqlite3").exists():
        print(f"  Store not found at {store_dir} — a full ingest is required.")
        return {"store": "uem", "status": "missing"}

    print("  Discovering URLs from Omnissa sitemaps...")
    all_xmls: list[str] = []
    for sitemap in DEFAULT_SITEMAPS:
        all_xmls.extend(_get_sub_sitemaps(sitemap))

    def _fetch(xml_url):
        try:
            res = requests.get(xml_url, headers={"User-Agent": USER_AGENT}, timeout=15)
            if res.status_code != 200:
                return []
            return [u for u in _parse_sitemap(res.content) if _should_ingest(u)]
        except Exception:
            return []

    live_urls: set[str] = set()
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(_fetch, x) for x in all_xmls]
        for future in as_completed(futures):
            live_urls.update(future.result())

    print(f"  Live sitemap URLs:    {_fmt(len(live_urls))}")

    vs = _open_store(store_dir)
    stored_urls = _distinct_sources(vs)
    print(f"  URLs in current store: {_fmt(len(stored_urls))}")

    new = live_urls - stored_urls
    removed = stored_urls - live_urls
    overlap = live_urls & stored_urls

    print(f"\n  New pages on Omnissa:  {_fmt(len(new))}")
    print(f"  Pages no longer live:  {_fmt(len(removed))}")
    print(f"  Pages unchanged (URL): {_fmt(len(overlap))}")

    # Show a sample of each
    for label, urls in (("New", new), ("Removed", removed)):
        if urls:
            print(f"\n  Sample {label} ({min(5, len(urls))} of {len(urls)}):")
            for u in sorted(urls)[:5]:
                print(f"    + {u}" if label == "New" else f"    - {u}")

    # Bundle-level summary of new pages
    if new:
        by_bundle: dict[str, int] = {}
        for u in new:
            b = _extract_bundle(u) or "(no bundle)"
            by_bundle[b] = by_bundle.get(b, 0) + 1
        top = sorted(by_bundle.items(), key=lambda kv: -kv[1])[:10]
        print(f"\n  New pages by bundle (top {len(top)}):")
        for b, n in top:
            print(f"    {n:>4}  {b}")

    # Normalize against the larger of live/stored so large removals don't
    # produce misleading >100% ratios.
    baseline = max(len(live_urls), len(stored_urls), 1)
    changed_frac = min((len(new) + len(removed)) / baseline, 1.0)
    verdict = _verdict(changed_frac, len(new), len(removed))
    print(f"\n  Change ratio: {changed_frac:.1%}")
    print(f"  Verdict: {verdict}")

    return {
        "store": "uem",
        "live": len(live_urls),
        "stored": len(stored_urls),
        "new": len(new),
        "removed": len(removed),
        "overlap": len(overlap),
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# API reference
# ---------------------------------------------------------------------------

def check_api(store_dir: str) -> dict:
    """Diff live Swagger endpoints against what's in the api Chroma store."""
    print("\n=== Checking API reference store ===")
    if not Path(store_dir, "chroma.sqlite3").exists():
        print(f"  Store not found at {store_dir} — a full ingest is required.")
        return {"store": "api", "status": "missing"}

    # Fetch live endpoint signatures per group
    live_sigs: dict[str, set[tuple[str, str]]] = {}  # group -> {(METHOD, path)}
    for name, url in API_MAP.items():
        try:
            res = requests.get(url, timeout=20)
            if res.status_code != 200:
                print(f"  {name}: live fetch failed ({res.status_code})")
                live_sigs[name] = set()
                continue
            data = res.json()
            sigs = set()
            for path, methods in (data.get("paths") or {}).items():
                for method in methods.keys():
                    sigs.add((method.upper(), path))
            live_sigs[name] = sigs
        except Exception as e:
            print(f"  {name}: live fetch error: {e}")
            live_sigs[name] = set()

    vs = _open_store(store_dir)
    stored_sigs: dict[str, set[tuple[str, str]]] = {}
    for m in _iter_metadatas(vs):
        if not m:
            continue
        g = m.get("api_group")
        method = m.get("method")
        path = m.get("path")
        if g and method and path:
            stored_sigs.setdefault(g, set()).add((method, path))

    print(f"  {'Group':<15} {'Live':>6} {'Stored':>7} {'+New':>6} {'-Rem':>6}")
    total_new = total_removed = total_live = 0
    for group in sorted(set(live_sigs) | set(stored_sigs)):
        live = live_sigs.get(group, set())
        stored = stored_sigs.get(group, set())
        new = len(live - stored)
        removed = len(stored - live)
        total_new += new
        total_removed += removed
        total_live += len(live)
        print(f"  {group:<15} {len(live):>6} {len(stored):>7} {new:>6} {removed:>6}")

    changed_frac = (total_new + total_removed) / max(total_live, 1)
    verdict = _verdict(changed_frac, total_new, total_removed)
    print(f"\n  Total live endpoints: {_fmt(total_live)}")
    print(f"  New endpoints:        {_fmt(total_new)}")
    print(f"  Removed endpoints:    {_fmt(total_removed)}")
    print(f"  Change ratio:         {changed_frac:.1%}")
    print(f"  Verdict: {verdict}")

    return {
        "store": "api",
        "live": total_live,
        "new": total_new,
        "removed": total_removed,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Release notes
# ---------------------------------------------------------------------------

def check_release_notes(store_dir: str) -> dict:
    """Report whether release-notes files have content changes vs the store.

    Uses a SHA-256 of each v{version}_rn.txt compared against a hash stored
    alongside the store in .content-hashes.txt (written by ingest if present).
    Falls back to 'unknown' when no hash file exists.
    """
    print("\n=== Checking release notes store ===")
    if not Path(store_dir, "chroma.sqlite3").exists():
        print(f"  Store not found at {store_dir} — a full ingest is required.")
        return {"store": "release_notes", "status": "missing"}

    vs = _open_store(store_dir)
    stored_versions = {m.get("version") for m in _iter_metadatas(vs) if m and m.get("version")}

    configured = set(VERSION_MAP.keys())
    new_versions = configured - stored_versions
    removed_versions = stored_versions - configured

    print(f"  Configured versions: {sorted(configured)}")
    print(f"  Versions in store:   {sorted(stored_versions)}")
    if new_versions:
        print(f"  Missing from store:  {sorted(new_versions)}")
    if removed_versions:
        print(f"  Extra in store:      {sorted(removed_versions)}")

    # Check local .txt files and hash them for content comparison
    hash_file = Path(store_dir) / ".content-hashes.txt"
    prior_hashes: dict[str, str] = {}
    if hash_file.exists():
        for line in hash_file.read_text().splitlines():
            if "=" in line:
                v, h = line.split("=", 1)
                prior_hashes[v.strip()] = h.strip()

    print(f"\n  {'Version':<10} {'File found':<12} {'Content changed':<18}")
    changed = 0
    any_local = False
    for version in sorted(configured):
        path = _find_rn_file(version)
        if path is None:
            print(f"  {version:<10} {'no':<12} {'(skip)':<18}")
            continue
        any_local = True
        text = path.read_text(encoding="utf-8", errors="ignore")
        h = hashlib.sha256(text.encode()).hexdigest()
        prior = prior_hashes.get(version)
        if prior is None:
            status = "unknown (first run)"
        elif prior != h:
            status = "YES"
            changed += 1
        else:
            status = "no"
        print(f"  {version:<10} {'yes':<12} {status:<18}")

    if not any_local:
        print("\n  No v*_rn.txt files found locally — can't compare content.")
        print("  See INGEST_MACOS.md for where to put them.")

    if new_versions or removed_versions:
        verdict = "version set changed — rebuild recommended"
    elif changed:
        verdict = f"{changed} version(s) have updated content — rebuild recommended"
    elif any_local:
        verdict = "no changes — rebuild not needed"
    else:
        verdict = "unable to determine — download release-notes files to compare"

    print(f"\n  Verdict: {verdict}")
    return {
        "store": "release_notes",
        "configured_versions": sorted(configured),
        "stored_versions": sorted(stored_versions),
        "missing_from_store": sorted(new_versions),
        "extra_in_store": sorted(removed_versions),
        "content_changed": changed,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Top-level driver
# ---------------------------------------------------------------------------

def check_all(targets: Iterable[str]) -> list[dict]:
    from wingman_mcp.config import get_store_dir

    results = []
    if "api" in targets:
        results.append(check_api(get_store_dir("api")))
    if "uem" in targets:
        results.append(check_uem(get_store_dir("uem")))
    if "release_notes" in targets:
        results.append(check_release_notes(get_store_dir("release_notes")))

    print("\n=== Summary ===")
    for r in results:
        print(f"  {r.get('store'):<15} {r.get('verdict', r.get('status', '?'))}")
    return results
