"""Ingest Omnissa web documentation into the UEM Chroma store."""
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

USER_AGENT = "WingmanMCP/1.0"
DOCS_API_HOST = "https://docs-be.omnissa.com"
SITEMAP_LOC_RE = re.compile(r"<loc>(.*?)</loc>", re.IGNORECASE | re.DOTALL)
RN_VERSION_RE = re.compile(r"Release-NotesV(2\d{3})", re.IGNORECASE)

DEFAULT_SITEMAPS = [
    "https://docs.omnissa.com/sitemap.xml",
    "https://developer.omnissa.com/sitemap.xml",
]
INCLUDE_KEYWORDS = [
    "workspace-one", "uem", "access", "intelligence", "hub",
    "techzone.omnissa.com/resource",
]
EXCLUDE_KEYWORDS = [
    "vdi", "app-volumes", "daas", "horizon",
    "techzone.omnissa.com/blog", "techzone.omnissa.com/users/",
    "?share=", "developer.omnissa.com", "/api/help/", "/apis/",
]
ALLOWED_FAMILIES = {"uem", "access", "hub", "intelligence"}

# Bundles that don't match INCLUDE_KEYWORDS but should be ingested.
# VSaaS preferred; unversioned kept only when no VSaaS variant exists.
EXTRA_BUNDLES = [
    # Device management guides
    "android-device-managementVSaaS",
    "ios-device-mgmtVSaaS",
    "macOS-Device-ManagementVSaaS",
    "LinuxDeviceManagementVSaaS",
    "ChromeOSDeviceMgmtVSaaS",
    "closednetworkandroidVSaaS",
    # App management
    "ApplicationManagementforAndroidVSaaS",
    "ApplicationManagementforiOSVSaaS",
    # Freestyle Orchestrator
    "Freestyle-Orchestrator-guideVSaaS",
    # Email / content / comms
    "WS1UEM-Secure-Email-GatewayVSaaS",
    "WS1UEM_MEM_GuideVSaaS",
    "WS1UEM_GmailIntegration_GuideVSaaS",
    "WS1UEM_ENS2_GuideVSaaS",
    "WS1UEM_KCD_SEGV2VSaaS",
    "WS1UEMMobileContentManagement",
    "AirWatchCloudMessagingVSaaS",
    # Tunnel
    "Workspace_ONE_TunnelVSaaS",
    # Assist
    "Workspace-ONE-AssistV25.11",
    "WorkspaceONE-RemoteHelpVSaaS",
    # Launcher
    "workspaceonelauncherVSaaS",
    # Drop Ship Provisioning
    "workspace_one_drop_ship_provisioningVSaaS",
    # PowerShell
    "WS1UEM_PowerShell_Integration_GuideVSaaS",
    # Boxer
    "WorkspaceONEBoxerAdminGuide",
    "WorkspaceONEBoxerAndroidUserGuide",
    "WorkspaceONEBoxeriOSUserGuide",
    # WS1 Web / Content / Send
    "WS1Web",
    "WS1ContentforAndroid",
    "WS1ContentforiOS",
    "WS1Send",
    # School
    "Airwatch-SchoolVSaaS",
    # Android readiness
    "GettingReadyforAndroidReleasesVSaaS",
    # Okta integration
    "workspaceone_okta_integration",
    # Outages
    "WS1Outages",
    # Release notes (component-specific)
    "Workspace_ONE_Tunnel_Android-RN",
    "Workspace_ONE_Tunnel_iOS-RN",
    "Workspace_ONE_Tunnel_macOS-RN",
    "Workspace_ONE_Tunnel_macOS_Appstore_Client-RN",
    "Workspace_ONE_Tunnel_Windows-RN",
    "Workspace_ONE_Tunnel_linux-RN",
    "Workspace_ONE_Tunnel_ChromeOS-RN",
    "Workspace_ONE_Tunnel_Container-RN",
    "WorkspaceONEBoxerforAndroidReleaseNotes",
    "WorkspaceONEBoxerforiOSReleaseNotes",
    "workspaceonelauncherforandroid-rn",
    "WS1AssistReleaseNotes",
    "WS1AssistAndroidReleaseNotes",
    "WS1AssistLinuxReleaseNotes",
    "WS1AssistWindowsDesktopReleaseNotes",
    "WorkspaceOneAssistmacOSReleaseNotes",
    "WS1ContentforAndroidRN",
    "WS1ContentforiOSRN",
    "WS1WebforAndroidRN",
    "WS1WebforiOSRN",
    "WS1SendforAndroidRN",
    "WS1SendforiOSRN",
    "WS1SoftwareDistributionAgentReleaseNotes",
    "ExpMgmtmacOSRN",
    "OmnissaPassReleaseNotes-Android",
    "OmnissaPassReleaseNotes-iOS",
    "PIVDManagerAndroidReleaseNotesVSaaS",
    "PIVDManageriOSReleaseNotesVSaaS",
    "workspace_one_drop_ship_provisioning-RN",
    "workspace-one-admin-assistant-for-macos-release-notesVSaaS",
    "chromeOSextention-rn",
    "WorkspaceONE-XRhub-ReleaseNotesVSaaS",
    "zebramxserviceforandroid-rnVSaaS",
    "honeywellserviceforandroidreleasenotes",
]
# Pre-compute set of lowercase bundle prefixes for fast matching.
_EXTRA_BUNDLE_SET = {b.lower() for b in EXTRA_BUNDLES}
# Skip versioned bundles (V23xx–V29xx) unless they are release notes.
_VERSIONED_BUNDLE_PATTERN = re.compile(r"V2[3-9]\d{2}", re.IGNORECASE)
_RELEASE_NOTES_BUNDLE_PATTERN = re.compile(r"(releasenotes|release-notes|-rn|_rn)", re.IGNORECASE)


def _parse_sitemap(content):
    text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)
    return [m.strip() for m in SITEMAP_LOC_RE.findall(text) if m.strip()]


def _get_sub_sitemaps(url):
    res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    if res.status_code != 200:
        return []
    return [loc for loc in _parse_sitemap(res.content) if loc.lower().endswith(".xml")]


def _extract_bundle(url):
    """Return the bundle name from a docs.omnissa.com URL, or None."""
    m = re.search(r"/bundle/([^/]+)/", url)
    return m.group(1) if m else None


def _should_ingest(url):
    low = url.lower()
    # Always ingest pages from explicitly listed bundles
    bundle = _extract_bundle(url)
    if bundle and bundle.lower() in _EXTRA_BUNDLE_SET:
        return True
    # Skip versioned bundles (V23xx–V29xx) unless they are release notes
    if bundle and _VERSIONED_BUNDLE_PATTERN.search(bundle) and not _RELEASE_NOTES_BUNDLE_PATTERN.search(bundle):
        return False
    return (
        any(k in low for k in INCLUDE_KEYWORDS)
        and not any(k in low for k in EXCLUDE_KEYWORDS)
    )


def _infer_family(url, topic_payload=None):
    haystack = (url or "").lower()
    bundle = ((topic_payload or {}).get("bundle_title") or "").lower()
    title = ((topic_payload or {}).get("title") or "").lower()
    description = (((topic_payload or {}).get("metadata") or {}).get("description") or "").lower()
    source_haystack = f"{haystack} {bundle}"
    content_haystack = f"{title} {description}"
    combined = f"{source_haystack} {content_haystack}"
    # Extra bundles are all UEM-ecosystem content
    url_bundle = _extract_bundle(url)
    if url_bundle and url_bundle.lower() in _EXTRA_BUNDLE_SET:
        return "uem"
    if any(k in source_haystack for k in ("workspace-one-uem", "workspaceone-uem", "workspace one uem", "/uem", "airwatch")):
        return "uem"
    if any(k in source_haystack for k in ("workspace one access", "omnissa access")):
        return "access"
    if "intelligence" in source_haystack:
        return "intelligence"
    if any(k in source_haystack for k in ("intelligent hub", "workspace one hub", "hub services")):
        return "hub"
    if any(k in content_haystack for k in ("workspace-one-uem", "workspaceone-uem", "workspace one uem", "airwatch")):
        return "uem"
    if any(k in content_haystack for k in ("workspace one access", "omnissa access")):
        return "access"
    if "intelligence" in content_haystack:
        return "intelligence"
    if any(k in content_haystack for k in ("intelligent hub", "workspace one hub", "hub services")):
        return "hub"
    return "general"


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
        res = requests.get(api_url, timeout=15, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US"})
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

    res = requests.get(url, timeout=10, headers={"User-Agent": USER_AGENT})
    if res.status_code != 200:
        return None
    soup = BeautifulSoup(res.content, "html.parser")
    for s in soup(["script", "style"]):
        s.decompose()
    return {"text": soup.get_text(separator=" ", strip=True), "topic_payload": None}


def _download(url):
    try:
        extracted = _extract_text(url)
        if not extracted:
            return None
        family = _infer_family(url, extracted.get("topic_payload"))
        if family not in ALLOWED_FAMILIES:
            return None
        text = extracted["text"]
        meta = {"source": url, "product_family": family}
        tp = extracted.get("topic_payload") or {}
        if tp.get("title"):
            meta["title"] = tp["title"]
        if tp.get("bundle_title"):
            meta["bundle_title"] = tp["bundle_title"]
        version = RN_VERSION_RE.search(url or "")
        if version:
            meta.update({"version": version.group(1), "product": "Workspace ONE UEM", "type": "release_notes"})
        return {"doc": Document(page_content=text, metadata=meta), "hash": hashlib.sha256(text.encode()).hexdigest()}
    except Exception:
        return None


def _fmt_duration(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"


def ingest_docs(store_dir: str, embeddings, max_workers: int = 50, batch_size: int = 500):
    """Crawl Omnissa sitemaps and ingest UEM docs."""
    t0 = time.time()
    os.makedirs(store_dir, exist_ok=True)
    vectorstore = Chroma(persist_directory=store_dir, embedding_function=embeddings)
    splitter = RecursiveCharacterTextSplitter(chunk_size=2000, chunk_overlap=200)

    # --- Phase 1: Discover URLs ---
    print("\n=== Phase 1/3: Discovering URLs from sitemaps ===")
    all_xmls = []
    for sitemap in DEFAULT_SITEMAPS:
        print(f"  Expanding: {sitemap}")
        all_xmls.extend(_get_sub_sitemaps(sitemap))
    print(f"  Found {len(all_xmls)} sub-sitemaps")

    def _fetch_and_filter_sitemap(xml_url):
        res = requests.get(xml_url, headers={"User-Agent": USER_AGENT}, timeout=15)
        if res.status_code != 200:
            return []
        return [u for u in _parse_sitemap(res.content) if _should_ingest(u)]

    all_urls = []
    bundles_found = set()
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_fetch_and_filter_sitemap, x): x for x in all_xmls}
        for future in tqdm(as_completed(futures), total=len(all_xmls), desc="  Parsing sitemaps"):
            for u in future.result():
                all_urls.append(u)
                b = _extract_bundle(u)
                if b:
                    bundles_found.add(b)

    # Deduplicate URLs (sitemaps often have dupes across locales)
    all_urls = list(dict.fromkeys(all_urls))
    print(f"  {len(all_urls)} pages to ingest across {len(bundles_found)} bundles")

    # --- Phase 2: Download & extract ---
    print(f"\n=== Phase 2/3: Downloading pages ({max_workers} workers) ===")
    all_docs = []
    failed = 0
    skipped = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_download, u): u for u in all_urls}
        for future in tqdm(as_completed(futures), total=len(all_urls), desc="  Fetching",
                           unit="pg", smoothing=0.1):
            result = future.result()
            if result:
                all_docs.append(result["doc"])
            else:
                url = futures[future]
                bundle = _extract_bundle(url)
                if bundle and bundle.lower() in _EXTRA_BUNDLE_SET:
                    failed += 1
                else:
                    skipped += 1

    print(f"  Downloaded {len(all_docs)} pages ({failed} failed, {skipped} filtered out)")

    # --- Phase 3: Chunk & embed ---
    print(f"\n=== Phase 3/3: Chunking & embedding ===")
    chunks = splitter.split_documents(all_docs)
    print(f"  {len(chunks)} chunks to embed")

    total_added = 0
    chroma_limit = 5000
    for j in tqdm(range(0, len(chunks), chroma_limit), desc="  Embedding",
                  unit="batch"):
        batch = chunks[j : j + chroma_limit]
        vectorstore.add_documents(batch)
        total_added += len(batch)

    elapsed = time.time() - t0
    print(f"\n=== Done! {total_added} chunks added in {_fmt_duration(elapsed)} ===")
