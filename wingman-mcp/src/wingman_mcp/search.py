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

def search_api(query: str, db: Chroma, max_results: int = 10) -> List[Dict[str, str]]:
    """Search the API endpoint reference store."""
    search_query = f"Workspace ONE UEM API {query}".strip()

    # Vector search
    docs = db.similarity_search(search_query, k=max_results * 2, filter={"type": "api_endpoint"})

    # Lexical fallback if vector search returns nothing
    if not docs:
        docs = _lexical_api_fallback(db, query, limit=max_results)

    # Also get context docs
    context_docs = []
    for doc_type in ("api_documentation", "api_definition"):
        try:
            context_docs.extend(db.similarity_search(search_query, k=6, filter={"type": doc_type}))
        except Exception:
            pass

    combined = docs + context_docs
    filtered = [d for d in combined if not _is_boilerplate(d)]
    deduped = _dedup(filtered)

    # Score: prefer api_endpoint type
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


def _lexical_api_fallback(db: Chroma, query: str, limit: int = 8) -> List[Any]:
    token_set = set(_keyword_tokens(query))
    if not token_set:
        return []

    try:
        payload = db.get(where={"type": "api_endpoint"})
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
    max_results: int = 15,
) -> List[Dict[str, str]]:
    """Search the release notes store with optional version filter."""
    docs: List[Any] = []

    # Normalize version input
    if version:
        version = version.replace("v", "").strip()

    # Version-specific search
    if version:
        v_filter = {"$and": [{"version": version}, {"type": "release_notes"}]}
        docs.extend(db.similarity_search(query, k=max_results, filter=v_filter))

        # Component-focused searches for richer results
        for label in COMPONENT_LABELS.values():
            focus_query = f"Workspace ONE UEM {label} updates release notes"
            docs.extend(db.similarity_search(focus_query, k=5, filter=v_filter))
    else:
        # Search across all versions
        docs.extend(db.similarity_search(query, k=max_results * 2, filter={"type": "release_notes"}))

    filtered = [d for d in docs if not _is_boilerplate(d)]
    deduped = _dedup(filtered)

    # Score: prefer matching version, recency
    def score(doc):
        meta = getattr(doc, "metadata", {}) or {}
        s = 0
        if version and meta.get("version") == version:
            s += 50
        # Newer versions score higher
        v = meta.get("version", "")
        if v:
            try:
                s += int(v)  # e.g. 2602 > 2509 > 2506
            except ValueError:
                pass
        return s

    deduped.sort(key=score, reverse=True)
    return _format_results(deduped[:max_results])
