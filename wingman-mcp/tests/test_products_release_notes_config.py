"""Smoke tests on the PRODUCTS registry shape."""
from wingman_mcp.ingest.products import (
    PRODUCTS,
    ProductConfig,
    ReleaseNotesSource,
)


def test_release_notes_source_defaults():
    rn = ReleaseNotesSource(bundle_prefixes=["Foo"])
    assert rn.bundle_prefixes == ["Foo"]
    assert rn.bundle_exact == []
    assert rn.source_type == "docs_web"
    assert rn.version_re == r"V(\d{4}(?:\.\d+)?)"
    assert rn.section_splitter is None


def test_product_config_accepts_release_notes():
    cfg = ProductConfig(
        slug="foo",
        label="Foo",
        description="",
        release_notes=ReleaseNotesSource(bundle_prefixes=["FooRN"]),
    )
    assert cfg.release_notes is not None
    assert cfg.release_notes.bundle_prefixes == ["FooRN"]


def test_product_config_release_notes_default_none():
    cfg = ProductConfig(slug="foo", label="Foo", description="")
    assert cfg.release_notes is None


import pytest


_EXISTING_SLUGS_WITH_RN = [
    "uem",
    "horizon",
    "horizon_cloud",
    "app_volumes",
    "uag",
    "dem",
    "thinapp",
]


@pytest.mark.parametrize("slug", _EXISTING_SLUGS_WITH_RN)
def test_existing_product_has_release_notes(slug):
    cfg = PRODUCTS[slug]
    assert cfg.release_notes is not None, f"{slug} is missing release_notes config"


def test_uem_uses_txt_source():
    cfg = PRODUCTS["uem"]
    assert cfg.release_notes.source_type == "uem_txt"
    assert cfg.release_notes.section_splitter is not None


def test_dem_version_re_strips_underscores():
    """DEM bundle names look like Dynamic-Environment-Manager_2111.1_..."""
    import re
    cfg = PRODUCTS["dem"]
    m = re.search(cfg.release_notes.version_re, "Dynamic-Environment-Manager_2111.1_AdminGuide")
    assert m is not None
    assert m.group(1) == "2111.1"


def test_app_volumes_rn_bundle_prefixes():
    cfg = PRODUCTS["app_volumes"]
    assert any(p.startswith("AppVolumesReleaseNotes") for p in cfg.release_notes.bundle_prefixes)


_NEW_SLUGS = ["access", "intelligence", "identity_service"]


@pytest.mark.parametrize("slug", _NEW_SLUGS)
def test_new_product_registered(slug):
    assert slug in PRODUCTS, f"{slug} missing from PRODUCTS"


@pytest.mark.parametrize("slug", _NEW_SLUGS)
def test_new_product_has_docs_config(slug):
    cfg = PRODUCTS[slug]
    assert cfg.include_keywords, f"{slug} has no include_keywords for docs ingest"


@pytest.mark.parametrize("slug", _NEW_SLUGS)
def test_new_product_has_release_notes(slug):
    cfg = PRODUCTS[slug]
    assert cfg.release_notes is not None
    # All three are rolling/single-bundle RN.
    assert cfg.release_notes.bundle_exact, (
        f"{slug} should pin RN bundles via bundle_exact (single canonical bundle)"
    )


def test_total_product_count():
    assert len(PRODUCTS) == 10
