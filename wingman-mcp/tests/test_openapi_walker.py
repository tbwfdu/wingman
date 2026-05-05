"""Tests for the OpenAPI 2/3 walker used by multi-product API ingest."""
from langchain_core.documents import Document

from wingman_mcp.ingest.ingest_api import _walk_openapi


_OPENAPI_3_FIXTURE = {
    "openapi": "3.0.1",
    "servers": [{"url": "https://example.com/api/v1"}],
    "paths": {
        "/foo/{id}": {
            "get": {
                "summary": "Get a foo",
                "description": "Returns the foo by id.",
                "operationId": "getFoo",
                "tags": ["Foo"],
                "parameters": [{"name": "id", "in": "path", "required": True}],
            },
        },
        "/bar": {
            "post": {"summary": "Create a bar", "tags": ["Bar"]},
        },
    },
}


_SWAGGER_2_FIXTURE = {
    "swagger": "2.0",
    "schemes": ["https"],
    "host": "host.example.com",
    "basePath": "/api/v2",
    "paths": {
        "/baz": {
            "get": {"summary": "List bazzes"},
        },
    },
}


def test_walk_openapi_3_extracts_servers_url():
    docs = _walk_openapi(_OPENAPI_3_FIXTURE, product="horizon", api_group="horizon-server")
    full_urls = [d.metadata["full_url"] for d in docs]
    assert "https://example.com/api/v1/foo/{id}" in full_urls
    assert "https://example.com/api/v1/bar" in full_urls


def test_walk_openapi_2_falls_back_to_host_basepath():
    docs = _walk_openapi(_SWAGGER_2_FIXTURE, product="uag", api_group="uag")
    assert any(
        d.metadata["full_url"] == "https://host.example.com/api/v2/baz"
        for d in docs
    )


def test_walk_openapi_emits_one_doc_per_method():
    docs = _walk_openapi(_OPENAPI_3_FIXTURE, product="horizon", api_group="horizon-server")
    assert len(docs) == 2
    methods = {d.metadata["method"] for d in docs}
    assert methods == {"GET", "POST"}


def test_walk_openapi_metadata_includes_product_and_type():
    docs = _walk_openapi(_OPENAPI_3_FIXTURE, product="horizon", api_group="horizon-server")
    for d in docs:
        assert d.metadata["product"] == "horizon"
        assert d.metadata["type"] == "api_endpoint"
        assert d.metadata["api_group"] == "horizon-server"


def test_walk_openapi_ignores_non_method_keys():
    spec = {
        "openapi": "3.0.0",
        "servers": [{"url": ""}],
        "paths": {
            "/x": {
                "parameters": [],  # not a method
                "get": {"summary": "g"},
            },
        },
    }
    docs = _walk_openapi(spec, product="p", api_group="g")
    methods = [d.metadata["method"] for d in docs]
    assert methods == ["GET"]
