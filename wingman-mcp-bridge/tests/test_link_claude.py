"""Tests for `wingman-mcp link claude` config generation.

Avoids touching real keyring / config by monkeypatching the credential
helpers. Filesystem writes go to a tmp path.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from wingman_mcp_bridge import link


@pytest.fixture
def fake_creds(monkeypatch):
    """Pretend UEM + Horizon are configured; everything else is not."""
    store = {
        "uem": {
            "client_id": "uem-cid",
            "client_secret": "uem-secret",
            "token_url": "https://uem.example.com/token",
            "api_base_url": "https://uem.example.com",
        },
        "horizon": {
            "username": "alice",
            "password": "horizon-pass",
            "server_url": "https://horizon.example.com",
            "domain": "CORP",
        },
    }

    def fake_is_configured(product, env_name="default"):
        return product in store

    def fake_load(product, env_name="default"):
        return store.get(product)

    monkeypatch.setattr(link, "is_product_configured", fake_is_configured)
    monkeypatch.setattr(link, "load_product_credentials", fake_load)
    return store


@pytest.fixture(autouse=True)
def no_real_keychain(monkeypatch):
    """link._is_logged_in must not touch the real keychain in tests."""
    monkeypatch.setattr(link, "_is_logged_in", lambda server_url: False)


@pytest.fixture(autouse=True)
def pinned_command(monkeypatch):
    """Pin the resolved binary name so assertions don't depend on where
    wingman-mcp-bridge happens to be installed in the test environment.

    Patches shutil.which (not bridge_command itself) so the resolution
    logic still runs and stays under test.
    """
    monkeypatch.setattr(link.shutil, "which", lambda name: "wingman-mcp-bridge")


def test_build_headers_includes_all_configured_products(fake_creds):
    headers = link.build_headers()
    # UEM headers (legacy names preserved)
    assert headers["X-UEM-Client-ID"] == "uem-cid"
    assert headers["X-UEM-Client-Secret"] == "uem-secret"
    assert headers["X-UEM-Token-URL"] == "https://uem.example.com/token"
    assert headers["X-UEM-API-URL"] == "https://uem.example.com"
    # Horizon headers
    assert headers["X-Horizon-Username"] == "alice"
    assert headers["X-Horizon-Password"] == "horizon-pass"
    assert headers["X-Horizon-Server-URL"] == "https://horizon.example.com"
    assert headers["X-Horizon-Domain"] == "CORP"


def test_build_headers_respects_product_filter(fake_creds):
    headers = link.build_headers(products=["uem"])
    assert "X-UEM-Client-ID" in headers
    assert not any(h.startswith("X-Horizon-") for h in headers)


def test_build_headers_empty_when_no_products_configured(monkeypatch):
    monkeypatch.setattr(link, "is_product_configured", lambda *a, **k: False)
    monkeypatch.setattr(link, "load_product_credentials", lambda *a, **k: None)
    assert link.build_headers() == {}


def test_bridge_entry_has_no_secrets():
    entry = link.bridge_entry("https://wingman.example.com/mcp")
    assert entry["command"] == "wingman-mcp-bridge"
    assert entry["args"] == ["serve", "--remote", "https://wingman.example.com/mcp"]
    assert "headers" not in entry
    # Belt and braces: no part of the entry should look like a secret.
    assert "secret" not in json.dumps(entry).lower()


def test_bridge_entry_uses_resolved_absolute_path(monkeypatch):
    """Claude Desktop's minimal GUI PATH needs an absolute command path."""
    monkeypatch.setattr(link.shutil, "which", lambda name: "/opt/bin/wingman-mcp-bridge")
    assert link.bridge_command() == "/opt/bin/wingman-mcp-bridge"


def test_bridge_command_falls_back_to_bare_name(monkeypatch):
    monkeypatch.setattr(link.shutil, "which", lambda name: None)
    assert link.bridge_command() == "wingman-mcp-bridge"


def test_merge_into_new_config(tmp_path):
    config_path = tmp_path / "claude_desktop_config.json"
    entry = link.bridge_entry("https://wingman.example.com/mcp")
    data, was_new = link.merge_into_claude_config(
        config_path, entry_name="wingman", entry=entry
    )
    assert was_new is True
    assert data["mcpServers"]["wingman"] == entry


def test_merge_preserves_other_mcp_servers(tmp_path):
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "other-server": {"command": "echo", "args": ["hi"]},
        },
        "unrelated_key": "preserved",
    }))
    data, was_new = link.merge_into_claude_config(
        config_path,
        entry_name="wingman",
        entry=link.bridge_entry("https://wingman.example.com/mcp"),
    )
    assert was_new is True
    assert "other-server" in data["mcpServers"]
    assert data["unrelated_key"] == "preserved"
    assert "wingman" in data["mcpServers"]


def test_merge_updates_existing_entry(tmp_path):
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text(json.dumps({
        "mcpServers": {
            "wingman": {
                "type": "http",
                "url": "https://old.example.com/mcp",
                "headers": {"X-UEM-Client-ID": "old"},
            },
        },
    }))
    new_entry = link.bridge_entry("https://wingman.example.com/mcp")
    data, was_new = link.merge_into_claude_config(
        config_path, entry_name="wingman", entry=new_entry
    )
    assert was_new is False
    # Old http/headers form fully replaced by the bridge form.
    assert data["mcpServers"]["wingman"] == new_entry
    assert "headers" not in data["mcpServers"]["wingman"]


def test_merge_rejects_malformed_existing_config(tmp_path):
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text("{ not valid json")
    with pytest.raises(RuntimeError, match="isn't valid JSON"):
        link.merge_into_claude_config(config_path, entry_name="x", entry={})


def test_link_claude_bridge_is_default(fake_creds, tmp_path, monkeypatch):
    """Default mode writes the keychain-backed bridge entry, no secrets."""
    desktop_path = tmp_path / "desktop.json"
    code_path = tmp_path / "code.json"
    monkeypatch.setattr(link, "claude_desktop_config_path", lambda: desktop_path)
    monkeypatch.setattr(link, "claude_code_config_path", lambda: code_path)
    buf = io.StringIO()
    rc = link.link_claude(
        client="both",
        server_url="https://wingman.example.com/mcp",
        entry_name="wingman",
        products=None,
        env_name="default",
        dry_run=False,
        out=buf,
    )
    assert rc == 0
    for p in (desktop_path, code_path):
        data = json.loads(p.read_text())
        entry = data["mcpServers"]["wingman"]
        assert entry["command"] == "wingman-mcp-bridge"
        assert entry["args"] == ["serve", "--remote", "https://wingman.example.com/mcp"]
        assert "headers" not in entry
    # No secret ever reaches the config file.
    assert "uem-secret" not in desktop_path.read_text()
    assert "horizon-pass" not in desktop_path.read_text()


def test_link_claude_bridge_writes_even_without_creds(monkeypatch, tmp_path):
    """Bridge mode is valid even with no tenant creds — it just warns."""
    monkeypatch.setattr(link, "is_product_configured", lambda *a, **k: False)
    monkeypatch.setattr(link, "load_product_credentials", lambda *a, **k: None)
    desktop_path = tmp_path / "desktop.json"
    monkeypatch.setattr(link, "claude_desktop_config_path", lambda: desktop_path)
    buf = io.StringIO()
    rc = link.link_claude(
        client="desktop",
        server_url="https://x/mcp",
        entry_name="wingman",
        products=None,
        env_name="default",
        dry_run=False,
        out=buf,
    )
    assert rc == 0
    assert desktop_path.exists()
    out = buf.getvalue()
    assert "wingman-mcp login" in out
    assert "wingman-mcp auth set" in out


def test_link_claude_legacy_headers_writes_inline_headers(fake_creds, tmp_path, monkeypatch):
    desktop_path = tmp_path / "desktop.json"
    monkeypatch.setattr(link, "claude_desktop_config_path", lambda: desktop_path)
    buf = io.StringIO()
    rc = link.link_claude(
        client="desktop",
        server_url="https://wingman.example.com/mcp",
        entry_name="wingman",
        products=None,
        env_name="default",
        dry_run=False,
        legacy_headers=True,
        out=buf,
    )
    assert rc == 0
    entry = json.loads(desktop_path.read_text())["mcpServers"]["wingman"]
    assert entry["type"] == "http"
    assert entry["headers"]["X-UEM-Client-ID"] == "uem-cid"
    assert "WARNING" in buf.getvalue()


def test_link_claude_legacy_headers_fails_without_creds(monkeypatch, tmp_path):
    monkeypatch.setattr(link, "is_product_configured", lambda *a, **k: False)
    monkeypatch.setattr(link, "load_product_credentials", lambda *a, **k: None)
    monkeypatch.setattr(link, "claude_desktop_config_path", lambda: tmp_path / "x.json")
    buf = io.StringIO()
    rc = link.link_claude(
        client="desktop",
        server_url="https://x/mcp",
        entry_name="wingman",
        products=None,
        env_name="default",
        dry_run=False,
        legacy_headers=True,
        out=buf,
    )
    assert rc == 1
    assert "wingman-mcp auth set" in buf.getvalue()


def test_link_claude_dry_run_writes_no_file(fake_creds, tmp_path, monkeypatch):
    desktop_path = tmp_path / "desktop.json"
    monkeypatch.setattr(link, "claude_desktop_config_path", lambda: desktop_path)
    buf = io.StringIO()
    rc = link.link_claude(
        client="desktop",
        server_url="https://wingman.example.com/mcp",
        entry_name="wingman",
        products=None,
        env_name="default",
        dry_run=True,
        out=buf,
    )
    assert rc == 0
    assert not desktop_path.exists()
    output = buf.getvalue()
    assert "Would write" in output
    assert '"command": "wingman-mcp-bridge"' in output


def test_claude_desktop_path_is_platform_aware(monkeypatch):
    """Each platform points at the right canonical config location."""
    monkeypatch.setattr(link.platform, "system", lambda: "Darwin")
    assert "Library/Application Support/Claude" in str(link.claude_desktop_config_path())

    monkeypatch.setattr(link.platform, "system", lambda: "Linux")
    assert ".config/Claude" in str(link.claude_desktop_config_path())

    monkeypatch.setattr(link.platform, "system", lambda: "Windows")
    monkeypatch.setenv("APPDATA", "/fake/appdata")
    assert "fake/appdata/Claude" in str(link.claude_desktop_config_path()).replace("\\", "/")
