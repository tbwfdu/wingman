"""`wingman-mcp link claude` — write a Wingman MCP entry into Claude configs.

Two forms of entry can be written:

  Bridge (default) — the Claude config holds only a `command`/`args` pair
    that launches `wingman-mcp serve --remote <url>`. The local bridge
    process injects the bearer token and per-tenant credentials from the
    OS keychain on every request, so nothing sensitive is written to
    claude_desktop_config.json / .claude.json.

  Legacy headers (`--legacy-headers`) — the older form: a `type: http`
    entry with the per-tenant credentials inlined as `X-*` headers. Kept
    only for environments that cannot run the local bridge binary; it
    writes secrets into the config file in plaintext.

Cross-platform config paths follow the published Claude conventions:

  Claude Desktop config:
    macOS    ~/Library/Application Support/Claude/claude_desktop_config.json
    Windows  %APPDATA%/Claude/claude_desktop_config.json
    Linux    ~/.config/Claude/claude_desktop_config.json

  Claude Code (CLI) global config:
    ~/.claude.json
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

from wingman_mcp.credentials import (
    SCHEMAS,
    is_product_configured,
    list_product_environments,
    load_product_credentials,
)


DEFAULT_SERVER_URL = "https://wingman.omnissafoundry.com/mcp"
DEFAULT_ENTRY_NAME = "wingman"


def claude_desktop_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Claude" / "claude_desktop_config.json"
        return Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def claude_code_config_path() -> Path:
    return Path.home() / ".claude.json"


def build_headers(
    products: Optional[list[str]] = None,
    env_name: str = "default",
) -> dict[str, str]:
    """Build the X-*-* header map for the configured products.

    Iterates the schema in declaration order; only products that have
    credentials saved AND a populated http_header_names are included.
    """
    headers: dict[str, str] = {}
    targets = products if products is not None else list(SCHEMAS.keys())
    for product in targets:
        schema = SCHEMAS.get(product)
        if schema is None:
            continue
        if not schema.http_header_names:
            continue
        if not is_product_configured(product, env_name):
            continue
        creds = load_product_credentials(product, env_name)
        if creds is None:
            continue
        for schema_field, header_name in schema.http_header_names.items():
            value = creds.get(schema_field)
            if value:
                headers[header_name] = value
    return headers


def bridge_command() -> str:
    """Absolute path to the wingman-mcp-bridge executable, or the bare name.

    Claude Desktop launches MCP servers with a minimal GUI PATH that does
    not include pip's user-bin directory, so a bare `wingman-mcp-bridge`
    command fails to spawn. Resolving the absolute path at link time avoids
    that; it falls back to the bare name only if the binary isn't found.
    """
    return shutil.which("wingman-mcp-bridge") or "wingman-mcp-bridge"


def bridge_entry(server_url: str) -> dict[str, Any]:
    """mcpServers entry that launches the local stdio bridge."""
    return {
        "command": bridge_command(),
        "args": ["serve", "--remote", server_url],
    }


def headers_entry(server_url: str, headers: dict[str, str]) -> dict[str, Any]:
    """Legacy mcpServers entry: direct HTTP with inlined credential headers."""
    return {
        "type": "http",
        "url": server_url,
        "headers": headers,
    }


def merge_into_claude_config(
    config_path: Path,
    entry_name: str,
    entry: dict[str, Any],
) -> tuple[dict, bool]:
    """Read config_path (or start fresh), merge in our mcpServers entry.

    Returns (new_config, was_new) where was_new is True if we created
    the entry, False if we updated an existing one.
    """
    data: dict[str, Any]
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Existing config at {config_path} isn't valid JSON: {exc}. "
                f"Fix or remove it before re-running."
            )
    else:
        data = {}
    mcp_servers = data.setdefault("mcpServers", {})
    was_new = entry_name not in mcp_servers
    mcp_servers[entry_name] = entry
    return data, was_new


def write_claude_config(config_path: Path, data: dict) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(config_path)


def link_claude(
    *,
    client: str,
    server_url: str,
    entry_name: str,
    products: Optional[list[str]],
    env_name: str,
    dry_run: bool,
    legacy_headers: bool = False,
    out=sys.stdout,
) -> int:
    """Implementation of `wingman-mcp link claude`. Returns an exit code."""
    if legacy_headers:
        entry = _legacy_headers_entry(server_url, products, env_name, out)
        if entry is None:
            return 1
    else:
        entry = bridge_entry(server_url)

    targets: list[Path] = []
    if client in ("desktop", "both"):
        targets.append(claude_desktop_config_path())
    if client in ("code", "both"):
        targets.append(claude_code_config_path())

    for path in targets:
        data, was_new = merge_into_claude_config(
            path, entry_name=entry_name, entry=entry
        )
        action = "Would write" if dry_run else ("Created" if was_new else "Wrote")
        print(f"{action} {path}", file=out)
        if dry_run:
            print(json.dumps(data, indent=2), file=out)
        else:
            write_claude_config(path, data)

    if legacy_headers:
        _report_legacy(entry, server_url, dry_run, out)
    else:
        _report_bridge(server_url, env_name, dry_run, out)
    return 0


def _legacy_headers_entry(
    server_url: str,
    products: Optional[list[str]],
    env_name: str,
    out,
) -> Optional[dict[str, Any]]:
    headers = build_headers(products=products, env_name=env_name)
    if not headers:
        print(
            "No configured products with headers found. Run "
            "`wingman-mcp auth set --product <slug>` first.",
            file=out,
        )
        return None
    return headers_entry(server_url, headers)


def _report_legacy(entry: dict, server_url: str, dry_run: bool, out) -> None:
    headers = entry.get("headers", {})
    products = sorted({h.split("-")[1] for h in headers if h.startswith("X-")})
    print(
        f"\nLinked entry against {server_url} with credential headers for: "
        f"{', '.join(products)}",
        file=out,
    )
    print(
        "WARNING: --legacy-headers writes credentials into the config file "
        "in plaintext. Prefer the default bridge mode, which keeps them in "
        "the OS keychain.",
        file=out,
    )
    if not dry_run:
        print("Restart Claude Desktop / Claude Code to pick up the new config.", file=out)


def _report_bridge(server_url: str, env_name: str, dry_run: bool, out) -> None:
    print(
        f"\nLinked bridge entry against {server_url}. Credentials stay in "
        f"your OS keychain; nothing sensitive was written to the config.",
        file=out,
    )
    # Surface prerequisites without failing — the config is still valid.
    if not _is_logged_in(server_url):
        print(
            f"  Next: run `wingman-mcp login --remote {server_url}` to sign in.",
            file=out,
        )
    configured = configured_products(env_name)
    if configured:
        print(
            f"  Tenant credentials found for: {', '.join(sorted(configured))}.",
            file=out,
        )
    else:
        print(
            "  No tenant credentials saved yet. Doc-search tools work without "
            "them; for UEM/Horizon tools run `wingman-mcp auth set --product <slug>`.",
            file=out,
        )
    if not dry_run:
        print("Restart Claude Desktop / Claude Code to pick up the new config.", file=out)


def _is_logged_in(server_url: str) -> bool:
    """True if a token bundle is cached for the remote server."""
    try:
        from wingman_mcp_bridge.oauth_client import load_bundle
        return load_bundle(server_url) is not None
    except Exception:
        return False


def configured_products(env_name: str = "default") -> list[str]:
    """Products that have stored credentials in the given env."""
    return [
        p for p in SCHEMAS
        if SCHEMAS[p].http_header_names and is_product_configured(p, env_name)
    ]
