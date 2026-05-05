"""RAG search logic adapted from wingman_core/chat/nodes/chatbot_tools.py."""
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_chroma import Chroma
from langchain_core.documents import Document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _keyword_tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9_/.-]+", (text or "").lower()) if len(t) >= 3]


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


def _metadata_text(doc: Any) -> str:
    meta = getattr(doc, "metadata", {}) or {}
    parts = [
        str(meta.get("source", "")),
        str(meta.get("full_url", "")),
        str(meta.get("type", "")),
        str(meta.get("api_group", "")),
        str(meta.get("product", "")),
        str(meta.get("product_family", "")),
        str(meta.get("section", "")),
    ]
    return " ".join(parts).lower()


def _is_boilerplate(doc: Any) -> bool:
    meta = getattr(doc, "metadata", {}) or {}
    if meta.get("type") in {"api_endpoint", "release_notes"}:
        return False
    content = (getattr(doc, "page_content", "") or "").lower()
    markers = [
        "skip to main content",
        "powered by zoomin software",
        "follow omnissa on linkedin",
        "our family sites omnissa.com",
        "legal center privacy notice terms & conditions",
    ]
    return sum(m in content for m in markers) >= 2


def _dedup(docs: List[Any]) -> List[Any]:
    seen = set()
    result = []
    for d in docs:
        text = (d.page_content or "").strip()
        fp = re.sub(r"\s+", " ", text.lower())[:300]
        if fp and fp not in seen:
            result.append(d)
            seen.add(fp)
    return result


def _format_results(docs: List[Any]) -> List[Dict[str, str]]:
    results = []
    for d in docs:
        meta = getattr(d, "metadata", {}) or {}
        is_api = meta.get("type") == "api_endpoint"
        source_meta = meta.get("source") or meta.get("full_url") or ""
        source_url = ""
        if not is_api and source_meta:
            if "/api/" not in source_meta and "/api/help/Docs" not in source_meta:
                source_url = source_meta
        results.append({
            "content": d.page_content,
            "source_url": source_url,
            "source": meta.get("source", "Documentation"),
            "section": meta.get("section") or meta.get("api_group") or meta.get("type", "general"),
        })
    return results


# ---------------------------------------------------------------------------
# Generic product documentation search (single-family stores)
# ---------------------------------------------------------------------------

def search_product_docs(
    query: str,
    db: Chroma,
    search_prefix: str = "",
    max_results: int = 10,
) -> List[Dict[str, str]]:
    """Search a single-product Chroma store (Horizon, App Volumes, etc.).

    Compared to `search_uem`, there is no multi-family scoring — every doc
    in the store belongs to one product, so we just vector-search, dedup,
    and return.
    """
    search_query = f"{search_prefix} {query}".strip() if search_prefix else query
    docs = db.similarity_search(search_query, k=max_results * 3)
    filtered = [d for d in docs if not _is_boilerplate(d)]
    deduped = _dedup(filtered)
    return _format_results(deduped[:max_results])


# ---------------------------------------------------------------------------
# UEM Documentation Search
# ---------------------------------------------------------------------------

def search_uem(query: str, db: Chroma, max_results: int = 10) -> List[Dict[str, str]]:
    """Search the UEM documentation store."""
    search_query = f"Workspace ONE UEM {query}".strip()
    docs = db.similarity_search(search_query, k=max_results * 3)

    # Filter and score
    filtered = [d for d in docs if not _is_boilerplate(d)]
    deduped = _dedup(filtered)

    # Preference scoring
    def score(doc):
        meta = getattr(doc, "metadata", {}) or {}
        haystack = _metadata_text(doc)
        s = 0
        if meta.get("product_family") == "uem":
            s += 40
        elif meta.get("product_family") in {"access", "hub", "intelligence"}:
            s += 20
        if "workspace one uem" in haystack or "workspace-one-uem" in haystack:
            s += 30
        if meta.get("type") == "release_notes":
            s -= 10  # Prefer docs over release notes in this tool
        return s

    deduped.sort(key=score, reverse=True)
    return _format_results(deduped[:max_results])


# ---------------------------------------------------------------------------
# API Reference Search
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Release Notes Search
# ---------------------------------------------------------------------------

COMPONENT_LABELS = {
    "windows_management": "Windows",
    "macos_management": "macOS",
    "ios_management": "iOS",
    "android_management": "Android",
    "core_platform": "Core UI & Platform",
    "user_management": "Users & Admin",
}

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
