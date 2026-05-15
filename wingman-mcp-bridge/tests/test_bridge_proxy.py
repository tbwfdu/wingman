"""Tests for the stdio<->remote MCP bridge (wingman_mcp.bridge).

The remote HTTP hop is replaced by monkeypatching `_remote_call`, so these
tests exercise header resolution and request forwarding without a real
MCP server or network.
"""
from __future__ import annotations

import mcp.types as types
import pytest

from wingman_mcp_bridge import bridge
from wingman_mcp_bridge.oauth_client import NotLoggedIn

REMOTE = "https://wingman.example.com/mcp"


# ---------------------------------------------------------------------------
# resolve_headers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_headers_merges_bearer_and_credentials(monkeypatch):
    async def fake_token(remote_url):
        assert remote_url == REMOTE
        return "tok-123"

    monkeypatch.setattr(bridge, "get_access_token", fake_token)
    monkeypatch.setattr(
        bridge, "build_headers",
        lambda env_name="default": {"X-UEM-Client-ID": "cid", "X-UEM-Client-Secret": "sec"},
    )
    headers = await bridge.resolve_headers(REMOTE)
    assert headers["Authorization"] == "Bearer tok-123"
    assert headers["X-UEM-Client-ID"] == "cid"
    assert headers["X-UEM-Client-Secret"] == "sec"


@pytest.mark.asyncio
async def test_resolve_headers_without_credentials_still_has_bearer(monkeypatch):
    async def fake_token(remote_url):
        return "tok-only"

    monkeypatch.setattr(bridge, "get_access_token", fake_token)
    monkeypatch.setattr(bridge, "build_headers", lambda env_name="default": {})
    headers = await bridge.resolve_headers(REMOTE)
    assert headers == {"Authorization": "Bearer tok-only"}


@pytest.mark.asyncio
async def test_resolve_headers_propagates_not_logged_in(monkeypatch):
    async def fake_token(remote_url):
        raise NotLoggedIn("not signed in")

    monkeypatch.setattr(bridge, "get_access_token", fake_token)
    with pytest.raises(NotLoggedIn):
        await bridge.resolve_headers(REMOTE)


@pytest.mark.asyncio
async def test_resolve_headers_passes_env_name_through(monkeypatch):
    seen = {}

    async def fake_token(remote_url):
        return "t"

    def fake_build(env_name="default"):
        seen["env"] = env_name
        return {}

    monkeypatch.setattr(bridge, "get_access_token", fake_token)
    monkeypatch.setattr(bridge, "build_headers", fake_build)
    await bridge.resolve_headers(REMOTE, env_name="staging")
    assert seen["env"] == "staging"


# ---------------------------------------------------------------------------
# build_server wiring
# ---------------------------------------------------------------------------

def test_build_server_registers_tool_handlers():
    server = bridge.build_server(REMOTE)
    registered = {k.__name__ for k in server.request_handlers}
    assert "ListToolsRequest" in registered
    assert "CallToolRequest" in registered
    assert server.name == "wingman-bridge"


# ---------------------------------------------------------------------------
# Request forwarding
#
# `_remote_call(remote_url, env_name, fn)` invokes `fn` against a live MCP
# ClientSession. The fakes below stand in for that session, so a single
# patched `_remote_call` routes both tools/list and tools/call correctly —
# the low-level Server caches tool definitions, which means a tools/call
# also drives a tools/list under the covers.
# ---------------------------------------------------------------------------

_REMOTE_TOOL = types.Tool(
    name="uem_search_devices",
    description="search",
    inputSchema={"type": "object"},
)


class _FakeSession:
    def __init__(self, call_result: types.CallToolResult | None = None):
        self._call_result = call_result

    async def list_tools(self):
        return types.ListToolsResult(tools=[_REMOTE_TOOL])

    async def call_tool(self, name, arguments=None):
        self.last_call = (name, arguments)
        return self._call_result


def _patch_remote_call(monkeypatch, session: _FakeSession, captured: dict):
    async def fake_remote_call(remote_url, env_name, fn):
        captured["remote_url"] = remote_url
        captured["env_name"] = env_name
        return await fn(session)

    monkeypatch.setattr(bridge, "_remote_call", fake_remote_call)


@pytest.mark.asyncio
async def test_list_tools_forwards_remote_result(monkeypatch):
    captured: dict = {}
    _patch_remote_call(monkeypatch, _FakeSession(), captured)
    server = bridge.build_server(REMOTE)
    handler = server.request_handlers[types.ListToolsRequest]
    result = await handler(types.ListToolsRequest(method="tools/list"))
    assert result.root.tools == [_REMOTE_TOOL]
    assert captured["remote_url"] == REMOTE


@pytest.mark.asyncio
async def test_call_tool_forwards_remote_result(monkeypatch):
    captured: dict = {}
    session = _FakeSession(types.CallToolResult(
        content=[types.TextContent(type="text", text="42 devices")],
        isError=False,
    ))
    _patch_remote_call(monkeypatch, session, captured)
    server = bridge.build_server(REMOTE, env_name="prod")
    handler = server.request_handlers[types.CallToolRequest]
    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(
            name="uem_search_devices", arguments={"query": "x"}
        ),
    )
    result = await handler(req)
    assert result.root.content[0].text == "42 devices"
    assert result.root.isError is False
    assert session.last_call == ("uem_search_devices", {"query": "x"})
    assert captured["env_name"] == "prod"


@pytest.mark.asyncio
async def test_call_tool_propagates_remote_error_result(monkeypatch):
    captured: dict = {}
    session = _FakeSession(types.CallToolResult(
        content=[types.TextContent(type="text", text="upstream 500")],
        isError=True,
    ))
    _patch_remote_call(monkeypatch, session, captured)
    server = bridge.build_server(REMOTE)
    handler = server.request_handlers[types.CallToolRequest]
    req = types.CallToolRequest(
        method="tools/call",
        params=types.CallToolRequestParams(name="uem_search_devices", arguments={}),
    )
    result = await handler(req)
    assert result.root.isError is True
    assert "upstream 500" in result.root.content[0].text


def test_default_remote_url_is_public_server():
    assert bridge.DEFAULT_REMOTE_URL == "https://wingman.omnissafoundry.com/mcp"
