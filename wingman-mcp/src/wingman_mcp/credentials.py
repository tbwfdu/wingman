"""Credential storage for product API access.

Supports multiple products (uem, horizon, app_volumes, …) and named environments
(e.g. "dev", "prod") so multiple tenants can be configured per product
simultaneously.

Each product registers a CredentialSchema declaring which fields are secret
(stored in the OS keychain via `keyring`) and which are non-secret config
(stored in ~/.wingman-mcp/config.json).  Environment variables override
everything and are namespaced as WINGMAN_MCP_<PRODUCT>_<FIELD>; the legacy
WINGMAN_MCP_<FIELD> names continue to work for UEM only.

Storage layout:
    keychain service    wingman-mcp.<product>.<env_name>
    config file         ~/.wingman-mcp/config.json
                        {"products": {<product>: {"environments": {<env>: {...}}}}}

A migration path translates the historical UEM-only flat config into the new
multi-product shape on first read.
"""
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, TypedDict

import keyring

SERVICE_BASE = "wingman-mcp"
CONFIG_FILE = Path.home() / ".wingman-mcp" / "config.json"


# ---------------------------------------------------------------------------
# Per-product credential schema registry
# ---------------------------------------------------------------------------

@dataclass
class CredentialSchema:
    """Declares the credential fields a product needs.

    secret_keys go to the OS keychain.  config_keys go to the JSON config
    file (non-secret).  env_var_aliases optionally maps legacy/unprefixed
    environment variable names to schema fields (currently used to keep the
    pre-multiproduct UEM env vars working).
    """
    product: str
    label: str
    secret_keys: tuple[str, ...]
    config_keys: tuple[str, ...]
    env_var_aliases: dict[str, str] = field(default_factory=dict)

    @property
    def all_fields(self) -> tuple[str, ...]:
        return self.secret_keys + self.config_keys


SCHEMAS: dict[str, CredentialSchema] = {
    "uem": CredentialSchema(
        product="uem",
        label="Workspace ONE UEM",
        secret_keys=("client_id", "client_secret"),
        config_keys=("token_url", "api_base_url"),
        # Legacy unprefixed env vars (predate multi-product support).
        env_var_aliases={
            "WINGMAN_MCP_CLIENT_ID": "client_id",
            "WINGMAN_MCP_CLIENT_SECRET": "client_secret",
            "WINGMAN_MCP_TOKEN_URL": "token_url",
            "WINGMAN_MCP_API_URL": "api_base_url",
        },
    ),
    "horizon": CredentialSchema(
        product="horizon",
        label="Horizon (Connection Server)",
        secret_keys=("username", "password"),
        config_keys=("server_url", "domain"),
    ),
    "horizon_cloud": CredentialSchema(
        product="horizon_cloud",
        label="Horizon Cloud Service",
        secret_keys=("client_id", "client_secret"),
        config_keys=("api_base_url", "org_id"),
    ),
    "app_volumes": CredentialSchema(
        product="app_volumes",
        label="App Volumes",
        secret_keys=("username", "password"),
        config_keys=("manager_url",),
    ),
    "access": CredentialSchema(
        product="access",
        label="Workspace ONE Access",
        secret_keys=("client_id", "client_secret"),
        config_keys=("tenant_url", "token_url"),
    ),
    "identity_service": CredentialSchema(
        product="identity_service",
        label="Omnissa Identity Service",
        secret_keys=("client_id", "client_secret"),
        config_keys=("tenant_url", "token_url"),
    ),
}


def get_schema(product: str) -> CredentialSchema:
    if product not in SCHEMAS:
        raise ValueError(
            f"Unknown product '{product}'. "
            f"Known: {sorted(SCHEMAS)}"
        )
    return SCHEMAS[product]


def known_products() -> list[str]:
    return list(SCHEMAS.keys())


# ---------------------------------------------------------------------------
# Backwards-compat: the original UEM-only TypedDict
# ---------------------------------------------------------------------------

class UEMCredentials(TypedDict):
    client_id: str
    client_secret: str
    token_url: str
    api_base_url: str


# Env-var names retained for callers that import them directly.
ENV_CLIENT_ID = "WINGMAN_MCP_CLIENT_ID"
ENV_CLIENT_SECRET = "WINGMAN_MCP_CLIENT_SECRET"
ENV_TOKEN_URL = "WINGMAN_MCP_TOKEN_URL"
ENV_API_URL = "WINGMAN_MCP_API_URL"


# ---------------------------------------------------------------------------
# Keychain / config helpers
# ---------------------------------------------------------------------------

def _service_name(product: str, env_name: str) -> str:
    """Keychain service name for a (product, env_name) pair."""
    return f"{SERVICE_BASE}.{product}.{env_name}"


def _legacy_uem_service_name(env_name: str) -> str:
    """Pre-multiproduct UEM keychain service name."""
    return f"{SERVICE_BASE}.{env_name}"


def _read_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def _write_config(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def _migrate_config(config: dict) -> dict:
    """Migrate old config layouts into the multi-product shape.

    Old A (pre-named-env): {"token_url": "...", "api_base_url": "..."}
        Keychain entries at "wingman-mcp" service.
    Old B (named-env, UEM-only):
        {"environments": {"<name>": {"token_url": "...", "api_base_url": "..."}}}
        Keychain entries at "wingman-mcp.<env>".
    New: {"products": {"<product>": {"environments": {...}}}}
        Keychain entries at "wingman-mcp.<product>.<env>".
    """
    if "products" in config:
        return config  # already migrated

    new_envs: dict = {}

    # --- Old A → Old B (in-memory) ---
    if "environments" not in config and (
        config.get("token_url") or config.get("api_base_url")
    ):
        token_url = config.pop("token_url", "")
        api_base_url = config.pop("api_base_url", "")
        # Migrate old flat keychain entries → wingman-mcp.default
        for key in ("client_id", "client_secret"):
            val = keyring.get_password(SERVICE_BASE, key)
            if val:
                keyring.set_password(_legacy_uem_service_name("default"), key, val)
                try:
                    keyring.delete_password(SERVICE_BASE, key)
                except keyring.errors.PasswordDeleteError:
                    pass
        new_envs["default"] = {
            "token_url": token_url,
            "api_base_url": api_base_url,
        }

    # --- Old B (named envs) → new ---
    for name, env_cfg in (config.get("environments") or {}).items():
        new_envs[name] = dict(env_cfg)
        # Move keychain entries from wingman-mcp.<env> → wingman-mcp.uem.<env>
        old_service = _legacy_uem_service_name(name)
        new_service = _service_name("uem", name)
        for key in ("client_id", "client_secret"):
            val = keyring.get_password(old_service, key)
            if val and not keyring.get_password(new_service, key):
                keyring.set_password(new_service, key, val)
                try:
                    keyring.delete_password(old_service, key)
                except keyring.errors.PasswordDeleteError:
                    pass

    new_config: dict = {"products": {}}
    if new_envs:
        new_config["products"]["uem"] = {"environments": new_envs}

    if new_envs or "environments" in config:
        # Only write back if we actually migrated something.
        _write_config(new_config)
    return new_config


def _get_product_envs(config: dict, product: str) -> dict:
    """Return the environments dict for a product (after migration)."""
    config = _migrate_config(config)
    return ((config.get("products") or {}).get(product) or {}).get("environments") or {}


# ---------------------------------------------------------------------------
# Per-product, per-env CRUD
# ---------------------------------------------------------------------------

def save_product_credentials(product: str, env_name: str, **fields: str) -> None:
    """Store credentials for (product, env_name).

    fields must cover every key in the product's schema.
    """
    schema = get_schema(product)
    missing = [k for k in schema.all_fields if not fields.get(k)]
    if missing:
        raise ValueError(
            f"Missing required fields for {product}: {missing}"
        )

    service = _service_name(product, env_name)
    for k in schema.secret_keys:
        keyring.set_password(service, k, fields[k])

    config = _read_config()
    config = _migrate_config(config)
    products = config.setdefault("products", {})
    product_block = products.setdefault(product, {})
    envs = product_block.setdefault("environments", {})

    cfg_values: dict = {}
    for k in schema.config_keys:
        v = fields[k]
        # Trim trailing slash on URL-shaped fields for consistency.
        if k.endswith("url") or k.endswith("_url"):
            v = v.rstrip("/")
        cfg_values[k] = v
    envs[env_name] = cfg_values
    _write_config(config)


def _env_var_value(schema: CredentialSchema, product: str, field_name: str) -> str:
    """Read an env-var override for a single schema field."""
    # Primary namespaced name: WINGMAN_MCP_<PRODUCT>_<FIELD>
    primary = f"WINGMAN_MCP_{product.upper()}_{field_name.upper()}"
    val = os.environ.get(primary, "").strip()
    if val:
        return val
    # Legacy aliases (UEM only, pre-multiproduct).
    for alias_name, alias_field in schema.env_var_aliases.items():
        if alias_field == field_name:
            v = os.environ.get(alias_name, "").strip()
            if v:
                return v
    return ""


def load_product_credentials(product: str, env_name: str = "default") -> Optional[dict]:
    """Load credentials for (product, env_name).

    Resolution order per field: env var → keychain (secrets) / config (non-secret).
    Returns None if any required field is missing.
    """
    schema = get_schema(product)
    service = _service_name(product, env_name)

    config = _read_config()
    env_config = _get_product_envs(config, product).get(env_name, {})

    out: dict = {}
    for key in schema.secret_keys:
        val = _env_var_value(schema, product, key)
        if not val:
            val = keyring.get_password(service, key) or ""
        out[key] = val
    for key in schema.config_keys:
        val = _env_var_value(schema, product, key)
        if not val:
            val = env_config.get(key, "")
        # Strip trailing slash on URL-shaped fields for consistency.
        if val and (key.endswith("url") or key.endswith("_url")):
            val = val.rstrip("/")
        out[key] = val

    if not all(out.get(k) for k in schema.all_fields):
        return None
    return out


def clear_product_credentials(product: str, env_name: str = "default") -> None:
    """Remove credentials for (product, env_name)."""
    schema = get_schema(product)
    service = _service_name(product, env_name)
    for key in schema.secret_keys:
        try:
            keyring.delete_password(service, key)
        except keyring.errors.PasswordDeleteError:
            pass

    config = _read_config()
    config = _migrate_config(config)
    products = config.get("products") or {}
    envs = (products.get(product) or {}).get("environments") or {}
    envs.pop(env_name, None)
    _write_config(config)


def list_product_environments(product: str) -> list[str]:
    """Return env names configured for a product."""
    config = _read_config()
    return sorted(_get_product_envs(config, product).keys())


def is_product_configured(product: str, env_name: str = "default") -> bool:
    return load_product_credentials(product, env_name) is not None


def get_product_status(product: str, env_name: Optional[str] = None) -> dict:
    """Multi-env status for a product. With env_name, returns just that env."""
    schema = get_schema(product)
    if env_name is not None:
        return _product_env_status(product, env_name)
    names = list_product_environments(product)
    if not names:
        return {"product": product, "configured_environments": 0, "environments": {}}
    return {
        "product": product,
        "configured_environments": len(names),
        "environments": {n: _product_env_status(product, n) for n in names},
    }


def _product_env_status(product: str, env_name: str) -> dict[str, str]:
    schema = get_schema(product)
    creds = load_product_credentials(product, env_name)
    if creds is None:
        # Build a partial status so users can see which fields are missing.
        partial: dict = {"configured": "no"}
        service = _service_name(product, env_name)
        config = _read_config()
        env_config = _get_product_envs(config, product).get(env_name, {})
        for k in schema.secret_keys:
            v = _env_var_value(schema, product, k) or keyring.get_password(service, k) or ""
            partial[k] = "(set)" if v else "(missing)"
        for k in schema.config_keys:
            v = _env_var_value(schema, product, k) or env_config.get(k, "")
            partial[k] = v or "(missing)"
        return partial
    out: dict = {"configured": "yes"}
    for k in schema.secret_keys:
        out[k] = _mask(creds[k]) if k in {"client_id"} else "(set)"
    for k in schema.config_keys:
        out[k] = creds[k]
    return out


# ---------------------------------------------------------------------------
# Cross-product status
# ---------------------------------------------------------------------------

def list_all_configured() -> dict[str, list[str]]:
    """{product: [env_names]} for every product that has at least one env."""
    out: dict[str, list[str]] = {}
    for p in known_products():
        envs = list_product_environments(p)
        if envs:
            out[p] = envs
    return out


# ---------------------------------------------------------------------------
# Backwards-compat: original UEM-only API.  These remain the entry points
# for existing callers (auth.py, server.py, cli.py).  Each is now a thin
# wrapper around the multi-product implementation, with product hard-coded
# to "uem".
# ---------------------------------------------------------------------------

def save_credentials(
    client_id: str,
    client_secret: str,
    token_url: str,
    api_base_url: str,
    env_name: str = "default",
) -> None:
    save_product_credentials(
        "uem", env_name,
        client_id=client_id,
        client_secret=client_secret,
        token_url=token_url,
        api_base_url=api_base_url,
    )


def load_credentials(env_name: str = "default") -> Optional[UEMCredentials]:
    creds = load_product_credentials("uem", env_name)
    if creds is None:
        return None
    return UEMCredentials(
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
        token_url=creds["token_url"],
        api_base_url=creds["api_base_url"],
    )


def list_environments() -> list[str]:
    return list_product_environments("uem")


def clear_credentials(env_name: str = "default") -> None:
    clear_product_credentials("uem", env_name)


def is_configured(env_name: str = "default") -> bool:
    return is_product_configured("uem", env_name)


def get_status(env_name: Optional[str] = None) -> dict:
    """Backwards-compatible UEM status.  Caller-visible shape unchanged."""
    if env_name is not None:
        return _product_env_status("uem", env_name)
    names = list_product_environments("uem")
    if not names:
        return {"configured_environments": 0, "environments": {}}
    return {
        "configured_environments": len(names),
        "environments": {n: _product_env_status("uem", n) for n in names},
    }


def _mask(value: str) -> str:
    if len(value) <= 8:
        return value[:2] + "***"
    return value[:4] + "***" + value[-4:]
