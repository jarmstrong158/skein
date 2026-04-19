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
    # FastMCP returns a CallToolResult or list of content blocks; normalize to text.
    if hasattr(result, "content"):
        text = result.content[0].text  # type: ignore[union-attr]
    elif isinstance(result, tuple):
        # Newer FastMCP versions return (content, structured) tuples.
        content = result[0]
        text = content[0].text if content else "null"
    else:
        text = result[0].text  # type: ignore[index]

    blob = json.loads(text)
    assert blob is not None
    assert blob["task_id"] == "mcp-task-001"
