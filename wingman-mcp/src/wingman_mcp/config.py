"""Store path resolution and configuration."""
import os
from pathlib import Path

# Base data dir for all stores.
DEFAULT_DATA_DIR = Path.home() / ".wingman-mcp" / "stores"


def get_data_dir() -> Path:
    """Return the base data directory, respecting WINGMAN_MCP_DATA_DIR env var."""
    return Path(os.environ.get("WINGMAN_MCP_DATA_DIR", str(DEFAULT_DATA_DIR)))


def _product_store_keys() -> tuple[str, ...]:
    """Lazy import to avoid pulling ingest deps into the runtime path."""
    try:
        from wingman_mcp.ingest.products import list_product_slugs
        return tuple(list_product_slugs())
    except Exception:
        # Ingest extras may not be installed in slim runtime distributions.
        # Fall back to the historical default.
        return ("uem",)


def get_store_keys() -> tuple[str, ...]:
    """Return the full set of valid store keys (products + api + release_notes)."""
    return (*_product_store_keys(), "api", "release_notes")


# STORE_KEYS is computed once at import for callers that read it as a constant.
# Use get_store_keys() if you need to pick up registry changes at runtime.
STORE_KEYS: tuple[str, ...] = get_store_keys()


def get_store_dir(store: str) -> str:
    """Return the directory path for a given store key."""
    valid = get_store_keys()
    if store not in valid:
        raise ValueError(f"Unknown store '{store}'. Expected one of: {valid}")
    env_var = f"WINGMAN_MCP_STORE_{store.upper()}_DIR"
    override = os.environ.get(env_var, "").strip()
    if override:
        return override
    return str(get_data_dir() / store)


def stores_exist() -> bool:
    """Check if at least the UEM store exists (the original gating store)."""
    uem_dir = Path(get_store_dir("uem"))
    return (uem_dir / "chroma.sqlite3").exists()
