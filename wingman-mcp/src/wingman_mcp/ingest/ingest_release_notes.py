"""Ingest Workspace ONE UEM release notes into Chroma."""
import os
import re
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

VERSION_MAP = {
    "2506": "https://docs.omnissa.com/bundle/Workspace-ONE-UEM-Release-NotesV2506/page/WorkspaceONEUEM-ReleaseNotes.html",
    "2509": "https://docs.omnissa.com/bundle/Workspace-ONE-UEM-Release-NotesV2509/page/WorkspaceONEUEM-ReleaseNotes.html",
    "2602": "https://docs.omnissa.com/bundle/Workspace-ONE-UEM-Release-NotesV2602/page/WorkspaceONEUEM-ReleaseNotes.html",
}

# Search for v{version}_rn.txt files in common locations
_SEARCH_DIRS = [
    Path.cwd(),
    Path.cwd().parent / "files",
    Path.cwd().parent / "archive" / "backups",
]


def _split_by_sections(text: str):
    sections = []
    current_section = "General"
    current_content = []
    for line in text.split("\n"):
        if re.match(r"^[A-Za-z ]+ (Management|Experience|Orchestrator|Architecture|Enrollment|Platform)$", line.strip()):
            if current_content:
                sections.append((current_section, "\n".join(current_content)))
            current_section = line.strip()
            current_content = []
        else:
            current_content.append(line)
    if current_content:
        sections.append((current_section, "\n".join(current_content)))
    return sections


def _find_rn_file(version: str) -> Path | None:
    filename = f"v{version}_rn.txt"
    for d in _SEARCH_DIRS:
        candidate = d / filename
        if candidate.exists():
            return candidate
    return None


def ingest_release_notes(store_dir: str, embeddings):
    """Ingest release notes into a Chroma store."""
    os.makedirs(store_dir, exist_ok=True)
    vectorstore = Chroma(persist_directory=store_dir, embedding_function=embeddings)
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)

    for version, url in VERSION_MAP.items():
        txt_file = _find_rn_file(version)
        if txt_file is None:
            print(f"  Skip v{version}: {version}_rn.txt not found")
            continue

        # Clean up existing
        existing = vectorstore.get(where={"version": version})
        existing_ids = existing.get("ids", [])
        if existing_ids:
            vectorstore.delete(ids=existing_ids)

        text = txt_file.read_text(encoding="utf-8")
        sections = _split_by_sections(text)

        docs = []
        for sec_name, sec_text in sections:
            header = f"Workspace ONE UEM Version {version} - {sec_name}\n\n"
            for chunk in splitter.split_text(sec_text):
                docs.append(Document(
                    page_content=header + chunk,
                    metadata={
                        "source": url,
                        "version": version,
                        "section": sec_name,
                        "product": "Workspace ONE UEM",
                        "product_family": "uem",
                        "type": "release_notes",
                    },
                ))

        if docs:
            vectorstore.add_documents(docs)
            print(f"  v{version}: {len(docs)} chunks")
