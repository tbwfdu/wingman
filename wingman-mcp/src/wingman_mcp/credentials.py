"""Credential storage for UEM environment configuration.

Secrets (client_id, client_secret) are stored in the OS keychain via `keyring`.
Non-secret config (token_url, api_base_url) is stored in ~/.wingman-mcp/config.json.
Environment variables override everything.
"""
import json
import os
import stat
from pathlib import Path
from typing import Optional, TypedDict

import keyring

SERVICE_NAME = "wingman-mcp"
CONFIG_FILE = Path.home() / ".wingman-mcp" / "config.json"

# Environment variable names
ENV_CLIENT_ID = "WINGMAN_MCP_CLIENT_ID"
ENV_CLIENT_SECRET = "WINGMAN_MCP_CLIENT_SECRET"
ENV_TOKEN_URL = "WINGMAN_MCP_TOKEN_URL"
ENV_API_URL = "WINGMAN_MCP_API_URL"


class UEMCredentials(TypedDict):
    client_id: str
    client_secret: str
    token_url: str
    api_base_url: str


def _read_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def _write_config(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


def save_credentials(
    client_id: str,
    client_secret: str,
    token_url: str,
    api_base_url: str,
) -> None:
    """Store credentials in OS keychain and config file."""
    keyring.set_password(SERVICE_NAME, "client_id", client_id)
    keyring.set_password(SERVICE_NAME, "client_secret", client_secret)

    config = _read_config()
    config["token_url"] = token_url
    config["api_base_url"] = api_base_url.rstrip("/")
    _write_config(config)


def load_credentials() -> Optional[UEMCredentials]:
    """Load credentials. Env vars take precedence over stored values."""
    client_id = os.environ.get(ENV_CLIENT_ID, "").strip()
    client_secret = os.environ.get(ENV_CLIENT_SECRET, "").strip()
    token_url = os.environ.get(ENV_TOKEN_URL, "").strip()
    api_base_url = os.environ.get(ENV_API_URL, "").strip()

    # Fill gaps from stored values
    if not client_id:
        client_id = keyring.get_password(SERVICE_NAME, "client_id") or ""
    if not client_secret:
        client_secret = keyring.get_password(SERVICE_NAME, "client_secret") or ""

    config = _read_config()
    if not token_url:
        token_url = config.get("token_url", "")
    if not api_base_url:
        api_base_url = config.get("api_base_url", "")

    if not all([client_id, client_secret, token_url, api_base_url]):
        return None

    return UEMCredentials(
        client_id=client_id,
        client_secret=client_secret,
        token_url=token_url,
        api_base_url=api_base_url.rstrip("/"),
    )


def clear_credentials() -> None:
    """Remove credentials from keychain and config file."""
    for key in ("client_id", "client_secret"):
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except keyring.errors.PasswordDeleteError:
            pass

    config = _read_config()
    config.pop("token_url", None)
    config.pop("api_base_url", None)
    _write_config(config)


def is_configured() -> bool:
    """Check if all required credentials are present."""
    return load_credentials() is not None


def get_status() -> dict[str, str]:
    """Return a summary of what's configured (secrets masked)."""
    creds = load_credentials()
    if creds is None:
        # Show what's missing
        client_id = os.environ.get(ENV_CLIENT_ID, "").strip() or keyring.get_password(SERVICE_NAME, "client_id") or ""
        client_secret = os.environ.get(ENV_CLIENT_SECRET, "").strip() or keyring.get_password(SERVICE_NAME, "client_secret") or ""
        config = _read_config()
        token_url = os.environ.get(ENV_TOKEN_URL, "").strip() or config.get("token_url", "")
        api_base_url = os.environ.get(ENV_API_URL, "").strip() or config.get("api_base_url", "")
        return {
            "configured": "no",
            "client_id": _mask(client_id) if client_id else "(missing)",
            "client_secret": "(set)" if client_secret else "(missing)",
            "token_url": token_url or "(missing)",
            "api_base_url": api_base_url or "(missing)",
        }
    return {
        "configured": "yes",
        "client_id": _mask(creds["client_id"]),
        "client_secret": "(set)",
        "token_url": creds["token_url"],
        "api_base_url": creds["api_base_url"],
    }


def _mask(value: str) -> str:
    if len(value) <= 8:
        return value[:2] + "***"
    return value[:4] + "***" + value[-4:]
