"""Pure function implementations of the MCP tools.

These are kept transport-agnostic so they can be unit tested without an MCP
client. server.py wraps each one with the MCP tool decorator.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from typing import Any

from skein.failures.detector import (
    cascade_for,
    failure_patterns,
    recent_failures,
)
from skein.timeline.builder import build, to_dict


def get_recent_failures(
    conn: sqlite3.Connection, *, hours: int = 1, limit: int = 20
) -> list[dict[str, Any]]:
    """Failed/rejected/canceled tasks within the last `hours` hours."""
    return recent_failures(conn, hours=hours, limit=limit)


def get_task_timeline(conn: sqlite3.Connection, task_id: str) -> dict[str, Any] | None:
    """Full ordered timeline for a task (messages, state transitions, artifacts)."""
    timeline = build(conn, task_id)
    if timeline is None:
        return None
    return to_dict(timeline)


def list_active_agents(
    conn: sqlite3.Connection, *, since_minutes: int = 60
) -> list[dict[str, Any]]:
    """Agents seen in the last `since_minutes` minutes."""
    rows = conn.execute(
        f"""
        SELECT a.id, a.name, a.endpoint_url, a.last_seen_at, a.first_seen_at,
               (SELECT COUNT(*) FROM messages m
                 WHERE (m.from_agent_id = a.id OR m.to_agent_id = a.id)
                   AND m.captured_at > datetime('now', '-{int(since_minutes)} minutes')) AS recent_message_count
          FROM agents a
         WHERE a.last_seen_at > datetime('now', '-{int(since_minutes)} minutes')
         ORDER BY a.last_seen_at DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_agent_activity(
    conn: sqlite3.Connection, agent_id: str, *, hours: int = 24
) -> dict[str, Any]:
    """Counts and rates for one agent over the last `hours` hours."""
    base = conn.execute(
        f"""
        SELECT COUNT(*) AS message_count
          FROM messages
         WHERE (from_agent_id = ? OR to_agent_id = ?)
           AND captured_at > datetime('now', '-{int(hours)} hours')
        """,
        (agent_id, agent_id),
    ).fetchone()

    task_stats = conn.execute(
        f"""
        SELECT t.current_state, COUNT(DISTINCT t.id) AS c
          FROM tasks t
          JOIN messages m ON m.task_id = t.id
         WHERE (m.from_agent_id = ? OR m.to_agent_id = ?)
           AND m.captured_at > datetime('now', '-{int(hours)} hours')
         GROUP BY t.current_state
        """,
        (agent_id, agent_id),
    ).fetchall()
    state_counts = {r["current_state"]: r["c"] for r in task_stats}
    total = sum(state_counts.values())
    failed = sum(state_counts.get(s, 0) for s in ("failed", "rejected", "canceled"))
    return {
        "agent_id": agent_id,
        "hours": hours,
        "message_count": base["message_count"] if base else 0,
        "task_count": total,
        "task_states": state_counts,
        "failure_rate": (failed / total) if total else 0.0,
    }


def query_failure_patterns(conn: sqlite3.Connection, *, days: int = 7) -> list[dict[str, Any]]:
    """Group failures by error_code over the last `days` days."""
    return failure_patterns(conn, days=days)


def export_trace(
    conn: sqlite3.Connection, task_id: str, *, include_payloads: bool = True
) -> dict[str, Any] | None:
    """Self-contained JSON export of a task and its cascade.

    Suitable for attaching to a bug report.
    """
    timeline = build(conn, task_id)
    if timeline is None:
        return None
    blob = to_dict(timeline)

    if not include_payloads:
        for e in blob["events"]:
            if e.get("kind") == "message":
                e.pop("payload", None)

    blob["cascade"] = cascade_for(conn, task_id)
    blob["agents"] = []
    agent_ids = set()
    for e in blob["events"]:
        if e.get("kind") == "message":
            for k in ("from_agent_id", "to_agent_id"):
                if e.get(k):
                    agent_ids.add(e[k])
    if agent_ids:
        placeholders = ",".join("?" for _ in agent_ids)
        for r in conn.execute(
            f"SELECT id, name, endpoint_url, card_json FROM agents WHERE id IN ({placeholders})",
            list(agent_ids),
        ).fetchall():
            agent = dict(r)
            if agent.get("card_json"):
                with contextlib.suppress(TypeError, ValueError):
                    agent["card"] = json.loads(agent.pop("card_json"))
            blob["agents"].append(agent)
    return blob
