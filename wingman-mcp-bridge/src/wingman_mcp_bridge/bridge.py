"""Stdio-to-remote MCP bridge.

`wingman-mcp serve --remote <url>` runs this: a local stdio MCP server that
forwards every request to a remote, Entra-protected HTTP MCP server. It
exists so a Claude config can stay a clean one-liner (`command` + `args`)
while credentials stay in the OS keychain — nothing sensitive lands in
claude_desktop_config.json / .claude.json.

Per request the bridge resolves two kinds of header:

  * `Authorization: Bearer <token>` — obtained/refreshed via oauth_client,
    backed by the keychain token cache.
  * `X-<Product>-*` — per-tenant API credentials, read from the keychain
    via the same path `wingman-mcp link claude` used to use.

Each forwarded call opens a fresh remote session, so a token refresh or a
credential change is picked up on the very next tool call without
restarting the bridge.
"""
from __future__ import annotations

import sys
from typing import Awaitable, Callable, TypeVar

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from wingman_mcp_bridge.link import build_headers
from wingman_mcp_bridge.oauth_client import NotLoggedIn, get_access_token

DEFAULT_REMOTE_URL = "https://wingman.omnissafoundry.com/mcp"

_T = TypeVar("_T")


async def resolve_headers(remote_url: str, env_name: str = "default") -> dict[str, str]:
    """Build the header set for one forwarded request.

    Raises NotLoggedIn (propagated from oauth_client) if no usable token
    is cached — callers should translate that into a 'run wingman-mcp
    login' message.
    """
    token = await get_access_token(remote_url)
    headers = {"Authorization": f"Bearer {token}"}
    headers.update(build_headers(env_name=env_name))
    return headers


async def _remote_call(
    remote_url: str,
    env_name: str,
    fn: Callable[[ClientSession], Awaitable[_T]],
) -> _T:
    """Open a fresh remote session, run `fn`, tear it down."""
    headers = await resolve_headers(remote_url, env_name)
    async with streamablehttp_client(remote_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def build_server(remote_url: str, env_name: str = "default") -> Server:
    """Construct the stdio Server that proxies to `remote_url`."""
    server: Server = Server("wingman-bridge")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        result = await _remote_call(remote_url, env_name, lambda s: s.list_tools())
        return result.tools

    # validate_input=False: the remote server is authoritative for schemas;
    # double-validating here only risks rejecting calls the remote accepts.
    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: dict) -> types.CallToolResult:
        return await _remote_call(
            remote_url, env_name, lambda s: s.call_tool(name, arguments)
        )

    return server


async def run(remote_url: str = DEFAULT_REMOTE_URL, env_name: str = "default") -> None:
    """Run the bridge over stdio. Exits non-zero if not signed in."""
    try:
        await get_access_token(remote_url)
    except NotLoggedIn as exc:
        sys.stderr.write(
            f"wingman-mcp bridge: {exc}\n"
            f"Sign in once with:  wingman-mcp login --remote {remote_url}\n"
        )
        sys.exit(1)

    server = build_server(remote_url, env_name)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())
