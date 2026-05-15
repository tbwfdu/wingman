"""Per-request context variables for HTTP server mode.

These ContextVars are populated by the HTTP transport's request middleware
before each MCP request is dispatched, allowing call_tool handlers to access
the caller's identity and credentials without any server-side storage. In
local stdio mode they keep their defaults.
"""
import contextvars
from dataclasses import dataclass
from typing import Literal, Optional

# Set to True for every HTTP request; False (default) in local stdio mode.
_is_http_request: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "is_http_request", default=False
)

# Per-product credentials from headers, keyed by product slug. UEM appears
# under "uem" (preserving the legacy shape that callers still expect). Other
# products: present only when ALL of their required fields were supplied as
# headers. RAG-only requests (no credentials) leave this as None.
#
# Helper getters are provided rather than have callers index directly so
# that the legacy UEM dict shape stays stable.
_request_credentials: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "request_credentials", default=None
)


def get_request_product_credentials(product: str) -> Optional[dict]:
    """Return the per-request credentials for `product`, or None.

    Returns None when not in HTTP mode, when no creds were set, or when
    this product's headers were absent.
    """
    bundle = _request_credentials.get()
    if not bundle:
        return None
    return bundle.get(product)


@dataclass(frozen=True)
class Principal:
    """Verified identity of the HTTP caller for a single request.

    Populated in HTTP mode from the request's validated identity token.
    `oid`, `tid`, `upn` are all None when `auth_method == "static_key"`.
    """

    oid: Optional[str]
    tid: Optional[str]
    upn: Optional[str]
    auth_method: Literal["entra", "static_key"]


# Populated on every authenticated HTTP request; None in stdio mode or
# before the request middleware has run.
_request_principal: contextvars.ContextVar[Optional[Principal]] = contextvars.ContextVar(
    "request_principal", default=None
)
