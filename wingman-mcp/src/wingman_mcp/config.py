"""Store path resolution and configuration."""
import os
from pathlib import Path

STORE_KEYS = ("uem", "api", "release_notes")

DEFAULT_DATA_DIR = Path.home() / ".wingman-mcp" / "stores"


def get_data_dir() -> Path:
    """Return the base data directory, respecting WINGMAN_MCP_DATA_DIR env var."""
    return Path(os.environ.get("WINGMAN_MCP_DATA_DIR", str(DEFAULT_DATA_DIR)))


def get_store_dir(store: str) -> str:
    """Return the directory path for a given store."""
    if store not in STORE_KEYS:
        raise ValueError(f"Unknown store '{store}'. Expected one of: {STORE_KEYS}")
    env_var = f"WINGMAN_MCP_STORE_{store.upper()}_DIR"
    override = os.environ.get(env_var, "").strip()
    if override:
        return override
    return str(get_data_dir() / store)


def stores_exist() -> bool:
    """Check if at least the UEM store exists."""
    uem_dir = Path(get_store_dir("uem"))
    return (uem_dir / "chroma.sqlite3").exists()
