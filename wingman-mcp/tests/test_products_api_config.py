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
