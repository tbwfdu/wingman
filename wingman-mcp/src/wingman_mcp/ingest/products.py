"""Registry of Omnissa product documentation sources for RAG ingestion.

Each entry describes how to crawl Omnissa docs sitemaps for one product:
which URLs to include/exclude, which bundles to force-include, and how to
label resulting chunks with a `product_family` metadata value.

Add a new product by appending an entry to PRODUCTS — no other code change
is required. The CLI and MCP tools read this registry at runtime.

Notes on filtering
------------------
* `include_keywords` / `exclude_keywords` are matched against the lowercased
  full URL.  A page is in scope when it matches at least one include keyword
  AND no exclude keyword.
* `extra_bundles` is a list of docs.omnissa.com bundle IDs that should be
  ingested unconditionally — useful for component bundles whose URLs don't
  contain any of the include keywords.
* `skip_versioned_bundles` defaults to True: archive bundles like
  `Foo-V2410` or `Foo-V25.11` are skipped (the unversioned / VSaaS variant
  is treated as canonical).  Release-notes bundles are always kept.
* `family_inference` (optional): a callable that returns the per-page
  `product_family` metadata.  If unset, every page is stamped with
  the product slug.  Used by the legacy `uem` product to keep
  UEM/Access/Hub/Intelligence in one combined store.
* `allowed_families` (optional): paired with `family_inference` — pages
  whose inferred family isn't in this set are dropped post-download.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, Optional


# ---------------------------------------------------------------------------
# UEM release-notes section splitter (extracted from legacy ingest_release_notes.py
# so it can be carried as a ProductConfig field).
# ---------------------------------------------------------------------------

import re as _re_rn

_UEM_SECTION_HEADING_RE = _re_rn.compile(
    r"^[A-Za-z ]+ "
    r"(Management|Experience|Orchestrator|Architecture|Enrollment|Platform)$"
)


def _uem_split_by_sections(text: str) -> list[tuple[str, str]]:
    """Split UEM release-notes text into (section_name, body) tuples."""
    sections: list[tuple[str, str]] = []
    current_section = "General"
    current_content: list[str] = []
    for line in text.split("\n"):
        if _UEM_SECTION_HEADING_RE.match(line.strip()):
            if current_content:
                sections.append((current_section, "\n".join(current_content)))
            current_section = line.strip()
            current_content = []
        else:
            current_content.append(line)
    if current_content:
        sections.append((current_section, "\n".join(current_content)))
    return sections


# ---------------------------------------------------------------------------
# Shared exclusion lists
# ---------------------------------------------------------------------------

# Patterns that are never useful for RAG regardless of product.
_NEVER_INGEST = [
    "techzone.omnissa.com/blog",
    "techzone.omnissa.com/users/",
    "?share=",
    "developer.omnissa.com",
    "/api/help/",
    "/apis/",
]


# ---------------------------------------------------------------------------
# Family inference for the broad UEM ecosystem store
# ---------------------------------------------------------------------------

_UEM_ALLOWED_FAMILIES = {"uem", "hub"}


def _uem_extract_bundle(url: str) -> Optional[str]:
    import re
    m = re.search(r"/bundle/([^/]+)/", url or "")
    return m.group(1) if m else None


def _uem_family_inference(url: str, topic_payload: Optional[dict]) -> str:
    """Infer the WS1-ecosystem family of a docs page from its URL + payload.

    Returns one of: "uem", "access", "hub", "intelligence", or "general".
    """
    haystack = (url or "").lower()
    bundle = ((topic_payload or {}).get("bundle_title") or "").lower()
    title = ((topic_payload or {}).get("title") or "").lower()
    description = (((topic_payload or {}).get("metadata") or {}).get("description") or "").lower()
    source_haystack = f"{haystack} {bundle}"
    content_haystack = f"{title} {description}"

    # Pages from explicitly listed bundles are always UEM-ecosystem
    url_bundle = _uem_extract_bundle(url)
    if url_bundle:
        product = PRODUCTS.get("uem") if "PRODUCTS" in globals() else None
        if product and url_bundle.lower() in {b.lower() for b in product.extra_bundles}:
            return "uem"

    if any(k in source_haystack for k in (
        "workspace-one-uem", "workspaceone-uem", "workspace one uem",
        "/uem", "airwatch",
    )):
        return "uem"
    if any(k in source_haystack for k in ("workspace one access", "omnissa access")):
        return "access"
    if "intelligence" in source_haystack:
        return "intelligence"
    if any(k in source_haystack for k in (
        "intelligent hub", "workspace one hub", "hub services",
    )):
        return "hub"
    if any(k in content_haystack for k in (
        "workspace-one-uem", "workspaceone-uem", "workspace one uem", "airwatch",
    )):
        return "uem"
    if any(k in content_haystack for k in ("workspace one access", "omnissa access")):
        return "access"
    if "intelligence" in content_haystack:
        return "intelligence"
    if any(k in content_haystack for k in (
        "intelligent hub", "workspace one hub", "hub services",
    )):
        return "hub"
    return "general"


# ---------------------------------------------------------------------------
# ReleaseNotesSource
# ---------------------------------------------------------------------------

@dataclass
class ReleaseNotesSource:
    """How to discover and parse a product's release notes."""
    bundle_prefixes: list[str] = field(default_factory=list)
    bundle_exact:    list[str] = field(default_factory=list)
    source_type:     Literal["docs_web", "uem_txt"] = "docs_web"
    # Regex applied to a bundle name to extract the version string.
    # Default matches "V2603", "V25.11", "V2506.1", etc.
    version_re:      str = r"V(\d{4}(?:\.\d+)?)"
    # Optional callable: text -> [(section_name, section_text), ...]
    section_splitter: Optional[Callable[[str], list[tuple[str, str]]]] = None


# ---------------------------------------------------------------------------
# ApiSource
# ---------------------------------------------------------------------------

@dataclass
class ApiSource:
    """Where and how to fetch a product's REST API specification."""
    spec_url:    str
    api_group:   str
    spec_format: Literal["openapi_json", "openapi_yaml", "pdf"] = "openapi_json"
    version:     Optional[str] = None


# ---------------------------------------------------------------------------
# ProductConfig
# ---------------------------------------------------------------------------

@dataclass
class ProductConfig:
    slug: str
    label: str
    description: str
    include_keywords: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    extra_bundles: list[str] = field(default_factory=list)
    skip_versioned_bundles: bool = True
    # When set, used at download time to label / filter pages by sub-family.
    family_inference: Optional[Callable[[str, Optional[dict]], str]] = None
    allowed_families: Optional[set[str]] = None
    # Search-time prefix prepended to user queries to bias vector search
    # toward the right product.  E.g. "Omnissa Horizon".
    search_prefix: str = ""
    release_notes: Optional[ReleaseNotesSource] = None
    api: Optional[ApiSource] = None

    @property
    def store_key(self) -> str:
        """Canonical store key (matches the Chroma store dir name)."""
        return self.slug


# ---------------------------------------------------------------------------
# UEM extra-bundle list (preserved verbatim from prior ingest_docs.py)
# ---------------------------------------------------------------------------

_UEM_EXTRA_BUNDLES = [
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
    # ENS / SEG / Admin Assistant / XR Hub / PIV-D moved to dedicated products.
    "WS1UEM_MEM_GuideVSaaS",
    "WS1UEM_GmailIntegration_GuideVSaaS",
    "WS1UEMMobileContentManagement",
    "AirWatchCloudMessagingVSaaS",
    # Intelligent Hub per-platform RN (the Hub APP is family-merged into UEM)
    "workspace-one-intelligent-hub-for-ios-release-notesVSaaS",
    "workspace-one-intelligent-hub-for-macos-release-notesVSaaS",
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
    "workspace_one_drop_ship_provisioning-RN",
    "chromeOSextention-rn",
    "zebramxserviceforandroid-rnVSaaS",
    "honeywellserviceforandroidreleasenotes",
]


# ---------------------------------------------------------------------------
# PRODUCT REGISTRY
#
# Add new products here.  Each product becomes its own Chroma store at
# `<data_dir>/<slug>/`.  The keyword/bundle lists for newly added products
# are starting points — refine them after running an initial ingest and
# inspecting what got picked up.
# ---------------------------------------------------------------------------

PRODUCTS: dict[str, ProductConfig] = {
    # -----------------------------------------------------------------------
    # Workspace ONE UEM (and tightly related ecosystem: Access, Intelligence,
    # Intelligent Hub, plus all WS1-managed apps and components)
    # -----------------------------------------------------------------------
    "uem": ProductConfig(
        slug="uem",
        label="Workspace ONE UEM (UEM, Hub)",
        description=(
            "Workspace ONE UEM and Intelligent Hub — "
            "plus the WS1-managed apps (Tunnel, Assist, Boxer, Launcher, etc.). "
            "Access and Intelligence are now separate products with their own stores."
        ),
        include_keywords=[
            "workspace-one", "uem", "access", "intelligence", "hub",
        ],
        exclude_keywords=[
            "vdi", "app-volumes", "daas", "horizon",
            # UAG / Access Gateway is Horizon-side
            "accessgateway", "access-gateway",
            # ThinApp is legacy Horizon packaging
            "thinapp",
            # Horizon Cloud Service
            "-hcs-", "/hcs-", "firstgen-hcs",
            # Access and Intelligence split out to separate stores
            "workspace-one-access", "workspaceoneaccess", "ws1-access",
            "ws1_access", "intelligence",
            # The following 10 sub-products are also their own stores now;
            # exclude their bundles from being scraped into the UEM store.
            "mobile-threat-defense", "mobilethreatdefense",
            "uemservicenow", "uem-servicenow",
            "hub-services",
            "xrhub",
            "pivdmanager",
            "admin-assistant",
            "ws1uem_ens", "ws1uemens",
            "ws1uem-secure-email", "ws1uem_kcd_seg", "ws1uemseg",
            "okta_scim",
            "airwatchcloudconnector",
            # TechZone is its own product
            "techzone.omnissa.com",
            *_NEVER_INGEST,
        ],
        extra_bundles=_UEM_EXTRA_BUNDLES,
        skip_versioned_bundles=True,
        family_inference=_uem_family_inference,
        allowed_families=_UEM_ALLOWED_FAMILIES,
        search_prefix="Workspace ONE UEM",
        release_notes=ReleaseNotesSource(
            # docs.omnissa.com bundles like Workspace-ONE-UEM-Release-NotesV2602
            bundle_prefixes=["Workspace-ONE-UEM-Release-Notes"],
            # When a local v{version}_rn.txt is present, also run the UEM
            # txt path (sectioned chunks). The dispatcher runs both paths
            # for products that configure bundle_prefixes AND uem_txt.
            source_type="uem_txt",
            version_re=r"V(\d{4})",
            section_splitter=_uem_split_by_sections,
        ),
    ),

    # -----------------------------------------------------------------------
    # Omnissa Horizon (8 / Enterprise on-prem VDI)
    # -----------------------------------------------------------------------
    # NOTE: with skip_versioned_bundles=True we only ingest unversioned /
    # current-release bundles (e.g. `Horizon-Administration` rather than
    # `Horizon-AdministrationV2603`). Add specific archive versions to
    # extra_bundles if you need historical content.
    "horizon": ProductConfig(
        slug="horizon",
        label="Omnissa Horizon",
        description="Horizon 8 / Horizon Enterprise on-prem VDI.",
        include_keywords=[
            "/horizon-", "/horizon/", "horizon-8", "horizon-console",
            "horizon-architecture", "horizon-installation",
            "horizon-administration", "horizon-security",
            "horizon-clients", "horizon-agents", "horizon-virtual-desktops",
        ],
        exclude_keywords=[
            "horizon-cloud", "-hcs-", "/hcs-", "firstgen-hcs", "daas",
            "app-volumes", "appvolumes",
            "accessgateway", "access-gateway", "unified-access-gateway",
            "thinapp",
            "dynamic-environment-manager",
            *_NEVER_INGEST,
        ],
        skip_versioned_bundles=True,
        search_prefix="Omnissa Horizon",
        release_notes=ReleaseNotesSource(
            bundle_prefixes=["Horizon-Release-Notes", "HorizonReleaseNotes"],
        ),
        api=ApiSource(
            spec_url="https://developer.omnissa.com/horizon-apis/horizon-server/versions/2603/rest-api-swagger-docs.json",
            api_group="horizon-server",
            spec_format="openapi_json",
            version="2603",
        ),
    ),

    # -----------------------------------------------------------------------
    # Horizon Cloud Service / DaaS
    # -----------------------------------------------------------------------
    "horizon_cloud": ProductConfig(
        slug="horizon_cloud",
        label="Horizon Cloud Service / DaaS",
        description="Omnissa Horizon Cloud Service (HCS) and DaaS offerings.",
        include_keywords=[
            "horizon-cloud", "horizoncloud",
            "/hcs-", "-hcs-", "/hcs/", "firstgen-hcs",
            "daas",
        ],
        exclude_keywords=[
            "app-volumes", "appvolumes",
            "accessgateway", "access-gateway",
            "thinapp",
            "dynamic-environment-manager",
            *_NEVER_INGEST,
        ],
        skip_versioned_bundles=True,
        search_prefix="Omnissa Horizon Cloud Service",
        release_notes=ReleaseNotesSource(
            bundle_exact=["HorizonCloudService-next-gen-ReleaseNotes"],
            version_re=r"$nope^",  # never matches → version defaults to "rolling"
        ),
        api=ApiSource(
            spec_url="https://developer.omnissa.com/horizon-apis/horizon-cloud-nextgen/horizon-cloud-nextgen-api-doc-public.yaml",
            api_group="horizon-cloud-nextgen",
            spec_format="openapi_yaml",
        ),
    ),

    # -----------------------------------------------------------------------
    # App Volumes
    # -----------------------------------------------------------------------
    # NOTE: App Volumes has no unversioned canonical bundle — every release
    # ships its own bundle (AppVolumesAdminGuideV2603, V2512, etc.).
    # We list the current release explicitly here; bump it when a new
    # version ships.
    "app_volumes": ProductConfig(
        slug="app_volumes",
        label="App Volumes",
        description="Omnissa App Volumes — real-time application delivery.",
        include_keywords=["app-volumes", "appvolumes"],
        exclude_keywords=[
            "horizon-cloud", "thinapp",
            *_NEVER_INGEST,
        ],
        extra_bundles=[
            "AppVolumesAdminGuideV2603",  # bump on each new App Volumes release
            "AppVolumesReleaseNotesV2603",
        ],
        skip_versioned_bundles=True,
        search_prefix="Omnissa App Volumes",
        release_notes=ReleaseNotesSource(
            bundle_prefixes=["AppVolumesReleaseNotes"],
        ),
        api=ApiSource(
            spec_url="https://developer.omnissa.com/app-volumes-apis/versions/2603/swagger.json",
            api_group="app-volumes",
            spec_format="openapi_json",
            version="2603",
        ),
    ),

    # -----------------------------------------------------------------------
    # Unified Access Gateway (UAG)
    # -----------------------------------------------------------------------
    "uag": ProductConfig(
        slug="uag",
        label="Unified Access Gateway",
        description="Omnissa Unified Access Gateway (UAG).",
        include_keywords=[
            "unified-access-gateway", "accessgateway", "access-gateway",
            "/uag-", "/uag/", "-uag-",
        ],
        exclude_keywords=[
            "horizon-cloud", "app-volumes", "thinapp",
            *_NEVER_INGEST,
        ],
        skip_versioned_bundles=True,
        search_prefix="Omnissa Unified Access Gateway",
        release_notes=ReleaseNotesSource(
            bundle_prefixes=["UnifiedAccessGatewayReleaseNotes"],
        ),
        api=ApiSource(
            spec_url="https://developer.omnissa.com/uag-rest-apis/rest-api-swagger.json",
            api_group="uag",
            spec_format="openapi_json",
        ),
    ),

    # -----------------------------------------------------------------------
    # ThinApp
    # -----------------------------------------------------------------------
    # Same versioning pattern as App Volumes — list the current release
    # bundles explicitly and bump on each new ThinApp release.
    "thinapp": ProductConfig(
        slug="thinapp",
        label="ThinApp",
        description="Legacy ThinApp application virtualization / packaging.",
        include_keywords=["thinapp"],
        exclude_keywords=list(_NEVER_INGEST),
        extra_bundles=[
            "ThinAppPackageiniParameterReferenceGuideV2603",
            "ThinAppUserGuideV2603",
            "ThinAppReleaseNotesV2603",
        ],
        skip_versioned_bundles=True,
        search_prefix="Omnissa ThinApp",
        release_notes=ReleaseNotesSource(
            bundle_prefixes=["ThinAppReleaseNotes"],
        ),
    ),

    # -----------------------------------------------------------------------
    # Dynamic Environment Manager (DEM)
    # -----------------------------------------------------------------------
    # DEM uses underscore-separated version suffixes in bundle names
    # (Dynamic-Environment-Manager_2111.1_...) which the standard
    # versioned-bundle regex doesn't catch — so we list current bundles
    # explicitly via extra_bundles instead.
    "dem": ProductConfig(
        slug="dem",
        label="Dynamic Environment Manager",
        description="Omnissa Dynamic Environment Manager (DEM, formerly UEM/User Environment Manager).",
        include_keywords=[
            "dynamic-environment-manager", "/dem-", "/dem/",
            "demadmin", "demreleasenotes",
        ],
        exclude_keywords=list(_NEVER_INGEST),
        skip_versioned_bundles=True,
        search_prefix="Omnissa Dynamic Environment Manager",
        release_notes=ReleaseNotesSource(
            bundle_prefixes=["Dynamic-Environment-Manager"],
            # DEM uses underscore-delimited versions in bundle names.
            version_re=r"_(\d{4}(?:\.\d+)?)_",
        ),
    ),

    # -----------------------------------------------------------------------
    # Workspace ONE Access (split out of the UEM ecosystem store)
    # -----------------------------------------------------------------------
    "access": ProductConfig(
        slug="access",
        label="Workspace ONE Access",
        description="Omnissa Workspace ONE Access (formerly Identity Manager).",
        include_keywords=[
            "workspace-one-access", "workspaceoneaccess", "ws1-access",
            "ws1_access", "AccessABM", "AccessEdgeDeviceSignals",
            "AccessPlatformSSO", "WorkspaceONEAccessDesktopClient",
        ],
        exclude_keywords=[
            "horizon-cloud", "app-volumes", "thinapp", "horizon-html-access",
            "unified-access-gateway", "accessgateway", "access-gateway",
            *_NEVER_INGEST,
        ],
        skip_versioned_bundles=True,
        search_prefix="Omnissa Workspace ONE Access",
        release_notes=ReleaseNotesSource(
            bundle_exact=[
                "workspace-one-access-release-notes",
                "workspace-one-access-release-notes-fedramp",
            ],
            bundle_prefixes=["workspace-one-access-release-notes"],
            # Access uses dotted yy.mm: V24.12, V23.09, etc.
            version_re=r"V?(\d{2}\.\d{2}(?:\.\d+\.\d+)?)",
        ),
        api=ApiSource(
            spec_url="https://developer.omnissa.com/omnissa-access-apis/openapi.json",
            api_group="omnissa-access",
            spec_format="openapi_json",
        ),
    ),

    # -----------------------------------------------------------------------
    # Workspace ONE Intelligence (split out of the UEM ecosystem store)
    # -----------------------------------------------------------------------
    "intelligence": ProductConfig(
        slug="intelligence",
        label="Workspace ONE Intelligence",
        description="Omnissa Workspace ONE Intelligence — analytics & automation.",
        include_keywords=["intelligence"],
        exclude_keywords=[
            "horizon", "app-volumes", "thinapp", "uem", "access",
            *_NEVER_INGEST,
        ],
        extra_bundles=["Intelligence"],
        skip_versioned_bundles=True,
        search_prefix="Omnissa Workspace ONE Intelligence",
        release_notes=ReleaseNotesSource(
            bundle_exact=["IntelligenceRN"],
            version_re=r"$nope^",  # never matches → "rolling"
        ),
        api=ApiSource(
            spec_url="https://developer.omnissa.com/omnissa-intelligence-apis/guides/DHUB-APIDocumentationforOmnissaIntelligence-V2-130326-183145.pdf",
            api_group="omnissa-intelligence",
            spec_format="pdf",
        ),
    ),

    # -----------------------------------------------------------------------
    # Omnissa Identity Service (new — no prior store)
    # -----------------------------------------------------------------------
    "identity_service": ProductConfig(
        slug="identity_service",
        label="Omnissa Identity Service",
        description="Omnissa Identity Service — cloud identity / authentication.",
        include_keywords=["identityservice", "identity-service"],
        exclude_keywords=[
            "horizon", "app-volumes", "thinapp", "uem", "access",
            "intelligence",
            *_NEVER_INGEST,
        ],
        extra_bundles=["IdentityServices", "IdentityServiceMigration"],
        skip_versioned_bundles=True,
        search_prefix="Omnissa Identity Service",
        release_notes=ReleaseNotesSource(
            bundle_exact=["identity-services-release-notes"],
            version_re=r"$nope^",  # rolling
        ),
        api=ApiSource(
            spec_url="https://developer.omnissa.com/omnissa-identity-service-api/omnissa-identity-service-api-doc.json",
            api_group="omnissa-identity-service",
            spec_format="openapi_json",
        ),
    ),

    # -----------------------------------------------------------------------
    # Workspace ONE Mobile Threat Defense
    # -----------------------------------------------------------------------
    "mtd": ProductConfig(
        slug="mtd",
        label="Workspace ONE Mobile Threat Defense",
        description="Omnissa Workspace ONE Mobile Threat Defense (MTD).",
        include_keywords=["mobile-threat-defense", "mobilethreatdefense"],
        exclude_keywords=list(_NEVER_INGEST),
        extra_bundles=["WorkspaceONE-MobileThreatDefenseVSaaS"],
        skip_versioned_bundles=True,
        search_prefix="Workspace ONE Mobile Threat Defense",
        # No dedicated RN bundle — updates ride in the rolling VSaaS bundle.
        release_notes=None,
    ),

    # -----------------------------------------------------------------------
    # Workspace ONE ServiceNow Integration
    # -----------------------------------------------------------------------
    "servicenow": ProductConfig(
        slug="servicenow",
        label="Workspace ONE ServiceNow Integration",
        description="Omnissa Workspace ONE UEM ↔ ServiceNow integration.",
        include_keywords=["uemservicenow", "uem-servicenow"],
        exclude_keywords=list(_NEVER_INGEST),
        extra_bundles=["WorkspaceONEUEMServiceNowIntegrationsVSaaS"],
        skip_versioned_bundles=True,
        search_prefix="Workspace ONE ServiceNow Integration",
        release_notes=ReleaseNotesSource(
            bundle_exact=["WorkspaceONEUEMServiceNowReleaseNotesVSaaS"],
            version_re=r"$nope^",
        ),
    ),

    # -----------------------------------------------------------------------
    # Workspace ONE Hub Services
    # -----------------------------------------------------------------------
    "hub_services": ProductConfig(
        slug="hub_services",
        label="Workspace ONE Hub Services",
        description=(
            "Omnissa Workspace ONE Hub Services — cloud catalog/notifications "
            "service backing the Intelligent Hub app."
        ),
        include_keywords=["hub-services"],
        exclude_keywords=list(_NEVER_INGEST),
        extra_bundles=["workspace-one-hub-services"],
        skip_versioned_bundles=True,
        search_prefix="Workspace ONE Hub Services",
        release_notes=ReleaseNotesSource(
            bundle_exact=["workspace-one-hub-services-release-notes"],
            version_re=r"$nope^",
        ),
    ),

    # -----------------------------------------------------------------------
    # Workspace ONE XR Hub
    # -----------------------------------------------------------------------
    "xr_hub": ProductConfig(
        slug="xr_hub",
        label="Workspace ONE XR Hub",
        description="Omnissa Workspace ONE XR Hub.",
        include_keywords=["xrhub", "xr-hub"],
        exclude_keywords=list(_NEVER_INGEST),
        extra_bundles=["WorkspaceONE-XRhubVSaaS"],
        skip_versioned_bundles=True,
        search_prefix="Workspace ONE XR Hub",
        release_notes=ReleaseNotesSource(
            bundle_exact=["WorkspaceONE-XRhub-ReleaseNotesVSaaS"],
            version_re=r"$nope^",
        ),
    ),

    # -----------------------------------------------------------------------
    # Workspace ONE PIV-D Manager
    # -----------------------------------------------------------------------
    "pivd_manager": ProductConfig(
        slug="pivd_manager",
        label="Workspace ONE PIV-D Manager",
        description="Omnissa Workspace ONE PIV-D Manager (PIV-derived credentials).",
        include_keywords=["pivdmanager", "pivd-manager"],
        exclude_keywords=list(_NEVER_INGEST),
        extra_bundles=["PIVDManagerGuideVSaaS"],
        skip_versioned_bundles=True,
        search_prefix="Workspace ONE PIV-D Manager",
        release_notes=ReleaseNotesSource(
            bundle_exact=[
                "PIVDManagerAndroidReleaseNotesVSaaS",
                "PIVDManageriOSReleaseNotesVSaaS",
            ],
            version_re=r"$nope^",
        ),
    ),

    # -----------------------------------------------------------------------
    # Workspace ONE Admin Assistant
    # -----------------------------------------------------------------------
    "admin_assistant": ProductConfig(
        slug="admin_assistant",
        label="Workspace ONE Admin Assistant",
        description="Omnissa Workspace ONE Admin Assistant (macOS).",
        include_keywords=["admin-assistant"],
        exclude_keywords=list(_NEVER_INGEST),
        extra_bundles=["Admin-AssistantVSaaS"],
        skip_versioned_bundles=True,
        search_prefix="Workspace ONE Admin Assistant",
        release_notes=ReleaseNotesSource(
            bundle_exact=[
                "workspace-one-admin-assistant-for-macos-release-notesVSaaS",
            ],
            version_re=r"$nope^",
        ),
    ),

    # -----------------------------------------------------------------------
    # Workspace ONE Email Notification Service (ENS / ENS2)
    # -----------------------------------------------------------------------
    "ens": ProductConfig(
        slug="ens",
        label="Workspace ONE Email Notification Service",
        description="Omnissa Workspace ONE Email Notification Service (ENS / ENS2).",
        include_keywords=["ws1uem_ens", "ws1uemens", "uem_ens"],
        exclude_keywords=list(_NEVER_INGEST),
        extra_bundles=["WS1UEM_ENS2_GuideVSaaS"],
        skip_versioned_bundles=True,
        search_prefix="Workspace ONE Email Notification Service",
        release_notes=ReleaseNotesSource(
            bundle_exact=["WS1UEMENSReleaseNotesVSaaS"],
            version_re=r"$nope^",
        ),
    ),

    # -----------------------------------------------------------------------
    # Workspace ONE Secure Email Gateway (SEG)
    # -----------------------------------------------------------------------
    "seg": ProductConfig(
        slug="seg",
        label="Workspace ONE Secure Email Gateway",
        description="Omnissa Workspace ONE Secure Email Gateway (SEG).",
        include_keywords=[
            "secure-email-gateway", "ws1uem-secure-email", "ws1uem_kcd_seg",
        ],
        exclude_keywords=list(_NEVER_INGEST),
        extra_bundles=[
            "WS1UEM-Secure-Email-GatewayVSaaS",
            "WS1UEM_KCD_SEGV2VSaaS",
        ],
        skip_versioned_bundles=True,
        search_prefix="Workspace ONE Secure Email Gateway",
        release_notes=ReleaseNotesSource(
            bundle_exact=["WS1UEMSEGReleaseNotesVSaaS"],
            version_re=r"$nope^",
        ),
    ),

    # -----------------------------------------------------------------------
    # Workspace ONE Okta SCIM Provisioning
    # -----------------------------------------------------------------------
    "okta_scim": ProductConfig(
        slug="okta_scim",
        label="Workspace ONE Okta SCIM Provisioning",
        description="Omnissa Workspace ONE Okta SCIM provisioning integration.",
        include_keywords=["okta_scim", "okta-scim"],
        exclude_keywords=list(_NEVER_INGEST),
        extra_bundles=["workspaceone_okta_scim_provisioning"],
        skip_versioned_bundles=True,
        search_prefix="Workspace ONE Okta SCIM Provisioning",
        # No dedicated RN bundle visible.
        release_notes=None,
    ),

    # -----------------------------------------------------------------------
    # Omnissa TechZone — cross-product reference content (best practices,
    # reference architectures, how-to guides, tutorials).
    # -----------------------------------------------------------------------
    "techzone": ProductConfig(
        slug="techzone",
        label="Omnissa TechZone",
        description=(
            "Omnissa TechZone reference content — best practices, "
            "reference architectures, how-to guides, and tutorials "
            "spanning the entire Omnissa product portfolio."
        ),
        include_keywords=["techzone.omnissa.com/resource"],
        exclude_keywords=[
            "techzone.omnissa.com/blog",
            "techzone.omnissa.com/users/",
            "?share=",
        ],
        # TechZone URLs aren't bundle-based, so versioned-bundle skipping
        # has no effect either way — leave at the default.
        skip_versioned_bundles=True,
        search_prefix="Omnissa TechZone",
        # No release-notes concept on TechZone — content is rolling.
        release_notes=None,
    ),

    # -----------------------------------------------------------------------
    # AirWatch Cloud Connector
    # -----------------------------------------------------------------------
    "aw_cloud_connector": ProductConfig(
        slug="aw_cloud_connector",
        label="AirWatch Cloud Connector",
        description=(
            "Omnissa AirWatch Cloud Connector (ACC) — links cloud UEM to "
            "on-prem directory and infrastructure services."
        ),
        include_keywords=["airwatchcloudconnector"],
        exclude_keywords=list(_NEVER_INGEST),
        extra_bundles=["AirWatchCloudConnectorVSaaS"],
        skip_versioned_bundles=True,
        search_prefix="AirWatch Cloud Connector",
        # No dedicated RN bundle visible.
        release_notes=None,
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def list_product_slugs() -> list[str]:
    """Return the canonical list of product slugs in registry order."""
    return list(PRODUCTS.keys())


def get_product(slug: str) -> ProductConfig:
    if slug not in PRODUCTS:
        raise ValueError(
            f"Unknown product '{slug}'. Known products: {', '.join(PRODUCTS)}"
        )
    return PRODUCTS[slug]
