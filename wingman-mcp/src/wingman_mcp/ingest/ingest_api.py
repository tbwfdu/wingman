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
