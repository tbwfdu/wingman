"""Per-request context variables for HTTP server mode.

These ContextVars are set by CredentialHeaderMiddleware before each MCP
request is dispatched, allowing call_tool handlers to access the
caller's UEM credentials without any server-side credential storage.
"""
import contextvars
from typing import Optional

# Set to True for every HTTP request; False (default) in local stdio mode.
_is_http_request: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "is_http_request", default=False
)

# Set to a UEMCredentials dict when all four X-UEM-* headers are present,
# or None when the headers are absent (RAG-only requests are still allowed).
_request_credentials: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "request_credentials", default=None
)
