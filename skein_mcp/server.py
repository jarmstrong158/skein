"""MCP stdio server exposing 6 Skein tools.

Run with: `skein-mcp` (after installing the [mcp] extra), or as
`python -m skein_mcp.server`. Reads SKEIN_DB_PATH from env, falling back
to ./data/skein.db.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from skein.db import open_db

from . import tools as t


DB_PATH = os.environ.get("SKEIN_DB_PATH", "./data/skein.db")

mcp = FastMCP("skein")


def _conn():
    return open_db(DB_PATH)


@mcp.tool()
def get_recent_failures(hours: int = 1, limit: int = 20) -> str:
    """List tasks that ended in failed/rejected/canceled state within the last `hours` hours.

    Returns JSON with task ids, error codes, error messages, and timestamps.
    Use this when the user asks 'what failed', 'recent failures', or 'what went wrong'.
    """
    conn = _conn()
    try:
        return json.dumps(t.get_recent_failures(conn, hours=hours, limit=limit), default=str)
    finally:
        conn.close()


@mcp.tool()
def get_task_timeline(task_id: str) -> str:
    """Return the full ordered timeline (messages, state transitions, artifacts)
    for a given A2A task id. Returns 'null' if the task is unknown.

    Use this when the user wants to see what happened during a specific task.
    """
    conn = _conn()
    try:
        return json.dumps(t.get_task_timeline(conn, task_id), default=str)
    finally:
        conn.close()


@mcp.tool()
def list_active_agents(since_minutes: int = 60) -> str:
    """List agents that exchanged messages within the last `since_minutes` minutes."""
    conn = _conn()
    try:
        return json.dumps(t.list_active_agents(conn, since_minutes=since_minutes), default=str)
    finally:
        conn.close()


@mcp.tool()
def get_agent_activity(agent_id: str, hours: int = 24) -> str:
    """Activity summary for one agent: message count, task count, failure rate."""
    conn = _conn()
    try:
        return json.dumps(t.get_agent_activity(conn, agent_id, hours=hours), default=str)
    finally:
        conn.close()


@mcp.tool()
def query_failure_patterns(days: int = 7) -> str:
    """Group failures by error_code over the last `days` days. Useful for
    'what's the most common failure pattern this week?'
    """
    conn = _conn()
    try:
        return json.dumps(t.query_failure_patterns(conn, days=days), default=str)
    finally:
        conn.close()


@mcp.tool()
def export_trace(task_id: str, include_payloads: bool = True) -> str:
    """Self-contained JSON export of a task: timeline, cascade, and agent cards.

    Suitable for attaching to a bug report. Set include_payloads=False to omit
    raw JSON-RPC bodies if they contain sensitive data.
    """
    conn = _conn()
    try:
        return json.dumps(t.export_trace(conn, task_id, include_payloads=include_payloads), default=str)
    finally:
        conn.close()


def main() -> None:
    if not Path(DB_PATH).exists():
        print(
            f"[skein-mcp] warning: SKEIN_DB_PATH={DB_PATH} does not exist yet. "
            "It will be created when first ingested.",
            file=sys.stderr,
        )
    mcp.run()


if __name__ == "__main__":
    main()
