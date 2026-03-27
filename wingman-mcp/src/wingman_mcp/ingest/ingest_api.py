"""Ingest Workspace ONE UEM API endpoint documentation from Swagger JSON."""
import json
import os
from datetime import datetime, timezone

import requests
from langchain_chroma import Chroma
from langchain_core.documents import Document

DEFAULT_HOST = "https://as1831.awmdm.com"
SANITIZED_HOST = "https://{your-uem-server}"

DOCS_PATH = "/api/help/Docs"
BASE_URL = f"{DEFAULT_HOST}{DOCS_PATH}"

API_MAP = {
    "MAM V1": f"{BASE_URL}/mamv1",
    "MAM V2": f"{BASE_URL}/mamv2",
    "MCM": f"{BASE_URL}/mcmv1",
    "MDM V1": f"{BASE_URL}/mdmv1",
    "MDM V2": f"{BASE_URL}/mdmv2",
    "MDM V3": f"{BASE_URL}/mdmv3",
    "MDM V4": f"{BASE_URL}/mdmv4",
    "MEM": f"{BASE_URL}/memv1",
    "System V1": f"{BASE_URL}/systemv1",
    "System V2": f"{BASE_URL}/systemv2",
}


def _sanitize_url(url: str) -> str:
    """Replace the real UEM hostname with a generic placeholder."""
    return url.replace(DEFAULT_HOST, SANITIZED_HOST)


def ingest_api(store_dir: str, embeddings):
    """Ingest API endpoints into a Chroma store."""
    os.makedirs(store_dir, exist_ok=True)
    vectorstore = Chroma(persist_directory=store_dir, embedding_function=embeddings)

    for name, url in API_MAP.items():
        print(f"Fetching {name}: {url}")
        try:
            res = requests.get(url, timeout=20)
            if res.status_code != 200:
                print(f"  Failed ({res.status_code}), skipping")
                continue

            data = res.json()
            base_api_url = ""
            if "servers" in data and data["servers"]:
                base_api_url = data["servers"][0].get("url", "").rstrip("/")

            paths = data.get("paths", {})
            docs = []
            for path, methods in paths.items():
                full_path = f"{base_api_url}{path}" if base_api_url else path
                for method, details in methods.items():
                    summary = details.get("summary", "")
                    description = details.get("description", "")
                    operation_id = details.get("operationId", "")
                    tags = ", ".join(details.get("tags", []))

                    safe_full_path = _sanitize_url(full_path)
                    safe_source = _sanitize_url(url)

                    content = f"""Workspace ONE UEM API Endpoint
Category: {name}
Full URL: {safe_full_path}
Path: {path}
Method: {method.upper()}
Summary: {summary}
Description: {description}
OperationId: {operation_id}
Tags: {tags}"""

                    docs.append(Document(
                        page_content=content.strip(),
                        metadata={
                            "source": safe_source,
                            "full_url": safe_full_path,
                            "path": path,
                            "method": method.upper(),
                            "type": "api_endpoint",
                            "api_group": name,
                            "product_family": "uem",
                        },
                    ))

            if docs:
                # Replace existing docs for this API group
                existing = vectorstore.get(where={"api_group": name})
                existing_ids = existing.get("ids", [])
                if existing_ids:
                    vectorstore.delete(ids=existing_ids)
                vectorstore.add_documents(docs)
                print(f"  Added {len(docs)} endpoints")

        except Exception as e:
            print(f"  Error: {e}")
