"""Credential storage for UEM environment configuration.

Supports named environments (e.g. "dev", "prod") so multiple UEM tenants
can be configured simultaneously.  Backward-compatible: existing single-env
configs are auto-migrated to the "default" environment on first access.

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

SERVICE_BASE = "wingman-mcp"
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


def _service_name(env_name: str) -> str:
    """Return the keyring service name for a given environment."""
    return f"{SERVICE_BASE}.{env_name}"


def _read_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def _write_config(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


def _migrate_config(config: dict) -> dict:
    """Migrate old flat config format to named-environments format.

    Old format:  {"token_url": "...", "api_base_url": "..."}
    New format:  {"environments": {"default": {"token_url": "...", "api_base_url": "..."}}}

    Also migrates keychain entries from old "wingman-mcp" service to
    "wingman-mcp.default".
    """
    if "environments" in config:
        return config  # already migrated

    # Extract old flat values
    token_url = config.pop("token_url", "")
    api_base_url = config.pop("api_base_url", "")

    # Migrate keychain entries from old service name
    old_service = SERVICE_BASE
    new_service = _service_name("default")
    for key in ("client_id", "client_secret"):
        val = keyring.get_password(old_service, key)
        if val:
            keyring.set_password(new_service, key, val)
            try:
                keyring.delete_password(old_service, key)
            except keyring.errors.PasswordDeleteError:
                pass

    new_config: dict = {"environments": {}}
    if token_url or api_base_url:
        new_config["environments"]["default"] = {
            "token_url": token_url,
            "api_base_url": api_base_url,
        }
    _write_config(new_config)
    return new_config


def _get_envs(config: dict) -> dict:
    """Return the environments dict, migrating if needed."""
    config = _migrate_config(config)
    return config.get("environments", {})


def save_credentials(
    client_id: str,
    client_secret: str,
    token_url: str,
    api_base_url: str,
    env_name: str = "default",
) -> None:
    """Store credentials for a named environment."""
    service = _service_name(env_name)
    keyring.set_password(service, "client_id", client_id)
    keyring.set_password(service, "client_secret", client_secret)

    config = _read_config()
    config = _migrate_config(config)
    envs = config.setdefault("environments", {})
    envs[env_name] = {
        "token_url": token_url,
        "api_base_url": api_base_url.rstrip("/"),
    }
    _write_config(config)


def load_credentials(env_name: str = "default") -> Optional[UEMCredentials]:
    """Load credentials for a named environment. Env vars take precedence."""
    client_id = os.environ.get(ENV_CLIENT_ID, "").strip()
    client_secret = os.environ.get(ENV_CLIENT_SECRET, "").strip()
    token_url = os.environ.get(ENV_TOKEN_URL, "").strip()
    api_base_url = os.environ.get(ENV_API_URL, "").strip()

    # Fill gaps from stored values
    service = _service_name(env_name)
    if not client_id:
        client_id = keyring.get_password(service, "client_id") or ""
    if not client_secret:
        client_secret = keyring.get_password(service, "client_secret") or ""

    config = _read_config()
    env_config = _get_envs(config).get(env_name, {})
    if not token_url:
        token_url = env_config.get("token_url", "")
    if not api_base_url:
        api_base_url = env_config.get("api_base_url", "")

    if not all([client_id, client_secret, token_url, api_base_url]):
        return None

    return UEMCredentials(
        client_id=client_id,
        client_secret=client_secret,
        token_url=token_url,
        api_base_url=api_base_url.rstrip("/"),
    )


def list_environments() -> list[str]:
    """Return the names of all configured environments."""
    config = _read_config()
    envs = _get_envs(config)
    # Include environments that have keychain entries even if config is sparse
    return sorted(envs.keys())


def clear_credentials(env_name: str = "default") -> None:
    """Remove credentials for a named environment."""
    service = _service_name(env_name)
    for key in ("client_id", "client_secret"):
        try:
            keyring.delete_password(service, key)
        except keyring.errors.PasswordDeleteError:
            pass

    config = _read_config()
    config = _migrate_config(config)
    envs = config.get("environments", {})
    envs.pop(env_name, None)
    _write_config(config)


def is_configured(env_name: str = "default") -> bool:
    """Check if all required credentials are present for an environment."""
    return load_credentials(env_name) is not None


def get_status(env_name: Optional[str] = None) -> dict:
    """Return a summary of what's configured (secrets masked).

    If env_name is None, returns status for all environments.
    If env_name is specified, returns status for that environment only.
    """
    if env_name is not None:
        return _env_status(env_name)

    # All environments
    names = list_environments()
    if not names:
        return {"configured_environments": 0, "environments": {}}
    return {
        "configured_environments": len(names),
        "environments": {name: _env_status(name) for name in names},
    }


def _env_status(env_name: str) -> dict[str, str]:
    """Return status for a single environment."""
    creds = load_credentials(env_name)
    if creds is None:
        service = _service_name(env_name)
        client_id = os.environ.get(ENV_CLIENT_ID, "").strip() or keyring.get_password(service, "client_id") or ""
        client_secret = os.environ.get(ENV_CLIENT_SECRET, "").strip() or keyring.get_password(service, "client_secret") or ""
        config = _read_config()
        env_config = _get_envs(config).get(env_name, {})
        token_url = os.environ.get(ENV_TOKEN_URL, "").strip() or env_config.get("token_url", "")
        api_base_url = os.environ.get(ENV_API_URL, "").strip() or env_config.get("api_base_url", "")
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
