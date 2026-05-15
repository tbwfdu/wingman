"""Sanity tests for per-request context variables."""
from wingman_mcp.request_context import (
    Principal,
    _is_http_request,
    _request_credentials,
    _request_principal,
)


def test_request_principal_defaults_to_none():
    assert _request_principal.get() is None


def test_principal_dataclass_is_frozen_and_holds_fields():
    p = Principal(oid="abc", tid="t1", upn="user@example.com", auth_method="entra")
    assert p.oid == "abc"
    assert p.tid == "t1"
    assert p.upn == "user@example.com"
    assert p.auth_method == "entra"

    try:
        p.oid = "changed"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Principal should be frozen")


def test_static_key_principal_allows_none_identity_fields():
    p = Principal(oid=None, tid=None, upn=None, auth_method="static_key")
    assert p.auth_method == "static_key"
    assert p.oid is None


def test_existing_contextvars_still_present():
    assert _is_http_request.get() is False
    assert _request_credentials.get() is None
