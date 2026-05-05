"""Smoke tests on the api configuration shape."""
import pytest

from wingman_mcp.ingest.products import (
    ApiSource,
    PRODUCTS,
    ProductConfig,
)


def test_api_source_defaults():
    src = ApiSource(spec_url="https://example/spec.json", api_group="grp")
    assert src.spec_format == "openapi_json"
    assert src.version is None


def test_product_config_accepts_api():
    cfg = ProductConfig(
        slug="foo",
        label="Foo",
        description="",
        api=ApiSource(spec_url="https://example/spec.json", api_group="grp"),
    )
    assert cfg.api is not None
    assert cfg.api.spec_url == "https://example/spec.json"


def test_product_config_api_default_none():
    cfg = ProductConfig(slug="foo", label="Foo", description="")
    assert cfg.api is None


_PRODUCTS_WITH_API = [
    "horizon",
    "horizon_cloud",
    "app_volumes",
    "uag",
    "access",
    "intelligence",
    "identity_service",
]

_PRODUCTS_WITHOUT_API = ["dem", "thinapp"]


@pytest.mark.parametrize("slug", _PRODUCTS_WITH_API)
def test_product_has_api(slug):
    cfg = PRODUCTS[slug]
    assert cfg.api is not None, f"{slug} should have an api config"
    assert cfg.api.spec_url.startswith("https://"), f"{slug} api spec_url is not https"
    assert cfg.api.api_group, f"{slug} api_group must not be empty"


@pytest.mark.parametrize("slug", _PRODUCTS_WITHOUT_API)
def test_product_without_api(slug):
    cfg = PRODUCTS[slug]
    assert cfg.api is None, f"{slug} must not have an api config (no REST API)"


def test_uem_keeps_legacy_api_map_path():
    """UEM does not use the new ApiSource — its API ingest is API_MAP-driven."""
    cfg = PRODUCTS["uem"]
    assert cfg.api is None


def test_intelligence_uses_pdf_format():
    cfg = PRODUCTS["intelligence"]
    assert cfg.api.spec_format == "pdf"


def test_horizon_cloud_uses_yaml_format():
    cfg = PRODUCTS["horizon_cloud"]
    assert cfg.api.spec_format == "openapi_yaml"
