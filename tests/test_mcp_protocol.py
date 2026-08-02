"""Smoke test the actual MCP wire protocol, not just the underlying tool fns.

If the `mcp` library changes its tool registration shape, this catches it.
"""

from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_mcp_server_lists_all_six_tools():
    from skein_mcp.server import mcp
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "get_recent_failures",
        "get_task_timeline",
        "list_active_agents",
        "get_agent_activity",
        "query_failure_patterns",
        "export_trace",
    }
    for t in tools:
        assert t.description, f"tool {t.name} has no description"


@pytest.mark.asyncio
async def test_mcp_call_tool_returns_json_string(monkeypatch, tmp_path):
    """Round-trip: register a fresh DB, ingest one payload, call get_task_timeline
    via the MCP `call_tool` path, parse the JSON it returns."""
    db_path = tmp_path / "mcp_smoke.db"

    # Point the server at our test DB
    import skein_mcp.server as srv
    monkeypatch.setattr(srv, "DB_PATH", str(db_path))

    # Seed a task by calling the underlying ingest
    from skein.db import open_db
    from skein.ingest.normalizer import store
    from skein.ingest.parser import parse
    conn = open_db(db_path)
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {
            "messageId": "m1", "role": "user",
            "parts": [{"kind": "text", "text": "hi"}],
            "taskId": "mcp-task-001", "contextId": "mcp-ctx",
        }},
    }
    store(conn, parse(payload), direction="outbound")
    conn.close()

    # Call through MCP machinery
    result = await srv.mcp.call_tool("get_task_timeline", {"task_id": "mcp-task-001"})
    # MCPServer returns a CallToolResult or list of content blocks; normalize to text.
    if hasattr(result, "content"):
        text = result.content[0].text  # type: ignore[union-attr]
    elif isinstance(result, tuple):
        # Some SDK versions return (content, structured) tuples.
        content = result[0]
        text = content[0].text if content else "null"
    else:
        text = result[0].text  # type: ignore[index]

    blob = json.loads(text)
    assert blob is not None
    assert blob["task_id"] == "mcp-task-001"


# --------------------------------------------------------------------------
# Conformance with MCP protocol revision 2026-07-28.
#
# These drive a real in-process client against the server so they exercise the
# actual dispatch path (where cache hints and result metadata are applied),
# not the convenience accessors on MCPServer, which bypass it.
# --------------------------------------------------------------------------

PROTOCOL_VERSION = "2026-07-28"

# Registration order in skein_mcp.server. Asserted explicitly rather than as
# "stable across two calls", so a reordering of the decorators is a test
# failure and a deliberate choice rather than a silent cache-hit regression
# for every client.
EXPECTED_TOOL_ORDER = [
    "get_recent_failures",
    "get_task_timeline",
    "list_active_agents",
    "get_agent_activity",
    "query_failure_patterns",
    "export_trace",
]


@pytest.fixture
def client():
    from mcp.client.client import Client

    from skein_mcp.server import mcp as server
    return Client(server)


@pytest.mark.asyncio
async def test_negotiates_2026_07_28(client):
    """The server speaks the new revision without an initialize handshake."""
    async with client as c:
        assert c.protocol_version == PROTOCOL_VERSION


@pytest.mark.asyncio
async def test_tools_list_carries_cache_hints(client):
    """SEP-2549: tools/list results must carry ttlMs and cacheScope.

    Checked on the serialized wire form, because the snake_case attributes
    would pass even if the camelCase aliases regressed.
    """
    async with client as c:
        result = await c.list_tools()
        wire = result.model_dump(by_alias=True, exclude_none=True)

    assert wire["ttlMs"] == 300_000
    assert wire["cacheScope"] == "public"


@pytest.mark.asyncio
async def test_tools_list_order_is_deterministic(client):
    """Servers SHOULD return tools in a deterministic order so clients can
    cache and LLM prompt caches keep hitting."""
    async with client as c:
        first = [t.name for t in (await c.list_tools()).tools]
        second = [t.name for t in (await c.list_tools()).tools]

    assert first == EXPECTED_TOOL_ORDER
    assert first == second


@pytest.mark.asyncio
async def test_results_carry_result_type(client):
    """Every result carries resultType; skein never needs a round trip, so
    all of its results are terminal."""
    async with client as c:
        result = await c.list_tools()
        wire = result.model_dump(by_alias=True, exclude_none=True)

    assert wire["resultType"] == "complete"


@pytest.mark.asyncio
async def test_server_identifies_itself_in_result_meta(client):
    """Servers SHOULD identify themselves in each result's _meta, now that
    there is no handshake in which to do it once."""
    async with client as c:
        result = await c.list_tools()
        wire = result.model_dump(by_alias=True, exclude_none=True)

    info = wire["_meta"]["io.modelcontextprotocol/serverInfo"]
    assert info["name"] == "skein"
    assert info["version"]


@pytest.mark.asyncio
async def test_server_discover_advertises_supported_versions(client):
    """Servers MUST implement server/discover. Clients may use it to select a
    version up front, or as a backward-compatibility probe on stdio."""
    async with client as c:
        discovered = await c.session.discover()
        wire = discovered.model_dump(by_alias=True, exclude_none=True)

    assert PROTOCOL_VERSION in wire["supportedVersions"]
    assert wire["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "skein"
    # server/discover is itself cacheable, and skein's answer is static.
    assert wire["ttlMs"] == 300_000
    assert wire["cacheScope"] == "public"
