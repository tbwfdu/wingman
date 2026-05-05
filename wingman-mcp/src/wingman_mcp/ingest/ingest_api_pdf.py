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
