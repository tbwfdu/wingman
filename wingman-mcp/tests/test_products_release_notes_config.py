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
