"""Failure detection over the captured trace store.

Two flavors:
  * Stale-task sweep — tasks past their timeout without reaching a terminal
    state get marked failed with a synthetic 'skein/timeout' error code.
  * Cascade detection — given a failed task, find tasks that referenced it
    (via message_references) or shared its contextId and themselves failed
    within a temporal window. Spec-derived, not heuristic.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..states import FAILURE_STATES, TERMINAL_STATES  # noqa: F401

TIMEOUT_ERROR_CODE = "skein/timeout"
TIMEOUT_ERROR_MESSAGE = "Task exceeded configured timeout without reaching a terminal state."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class StaleSweepResult:
    checked: int
    marked_failed: list[str]


def sweep_stale_tasks(
    conn: sqlite3.Connection,
    *,
    default_timeout_seconds: int,
    now: datetime | None = None,
) -> StaleSweepResult:
    """Mark non-terminal tasks past their effective timeout as failed.

    Effective timeout per task: tasks.timeout_seconds if set, else
    default_timeout_seconds.
    """
    now = now or datetime.now(timezone.utc)
    rows = conn.execute(
        """
        SELECT id, created_at, updated_at, timeout_seconds
          FROM tasks
         WHERE terminal_at IS NULL
        """
    ).fetchall()

    marked: list[str] = []
    for r in rows:
        timeout = r["timeout_seconds"] or default_timeout_seconds
        anchor = _parse_iso(r["updated_at"]) or _parse_iso(r["created_at"])
        if anchor is None:
            continue
        if now - anchor > timedelta(seconds=timeout):
            now_iso = now.isoformat()
            conn.execute("BEGIN")
            try:
                prev = conn.execute(
                    "SELECT current_state FROM tasks WHERE id = ?", (r["id"],)
                ).fetchone()
                if prev is None:
                    conn.execute("ROLLBACK")
                    continue
                conn.execute(
                    """
                    UPDATE tasks
                       SET current_state = 'failed',
                           updated_at    = ?,
                           terminal_at   = ?,
                           error_code    = COALESCE(error_code, ?),
                           error_message = COALESCE(error_message, ?)
                     WHERE id = ? AND terminal_at IS NULL
                    """,
                    (now_iso, now_iso, TIMEOUT_ERROR_CODE, TIMEOUT_ERROR_MESSAGE, r["id"]),
                )
                conn.execute(
                    """
                    INSERT INTO state_transitions (task_id, from_state, to_state, at, triggered_by_message_id)
                    VALUES (?, ?, 'failed', ?, NULL)
                    """,
                    (r["id"], prev["current_state"], now_iso),
                )
                conn.execute("COMMIT")
                marked.append(r["id"])
            except Exception:
                conn.execute("ROLLBACK")
                raise
    return StaleSweepResult(checked=len(rows), marked_failed=marked)


def recent_failures(conn: sqlite3.Connection, *, hours: int = 24, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT id, context_id, current_state, updated_at, terminal_at,
               error_code, error_message
          FROM tasks
         WHERE current_state IN ('failed','rejected','canceled')
           AND updated_at > datetime('now', '-{int(hours)} hours')
         ORDER BY updated_at DESC
         LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def failure_patterns(conn: sqlite3.Connection, *, days: int = 7) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT COALESCE(error_code, '(unknown)') AS error_code,
               COUNT(*) AS count,
               MAX(updated_at) AS latest_at
          FROM tasks
         WHERE current_state IN ('failed','rejected','canceled')
           AND updated_at > datetime('now', '-{int(days)} days')
         GROUP BY COALESCE(error_code, '(unknown)')
         ORDER BY count DESC
        """
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        examples = conn.execute(
            """
            SELECT id FROM tasks
             WHERE COALESCE(error_code, '(unknown)') = ?
               AND current_state IN ('failed','rejected','canceled')
             ORDER BY updated_at DESC
             LIMIT 5
            """,
            (r["error_code"],),
        ).fetchall()
        out.append({**dict(r), "example_task_ids": [e["id"] for e in examples]})
    return out


def cascade_for(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    window_seconds: int = 300,
) -> list[dict[str, Any]]:
    """Return tasks plausibly affected by the failure of `task_id`.

    Two signals (deterministic, both per A2A spec):
      1. Referenced via message_references (a message in another task names
         this one in referenceTaskIds).
      2. Same contextId, with a transition into a failed state within
         `window_seconds` after this task's terminal_at.
    """
    root = conn.execute(
        "SELECT id, context_id, terminal_at FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if root is None:
        return []

    related: dict[str, dict[str, Any]] = {}

    for r in conn.execute(
        """
        SELECT DISTINCT m.task_id, t.current_state, t.error_code, t.updated_at
          FROM message_references mr
          JOIN messages m ON m.id = mr.message_id
          JOIN tasks t    ON t.id = m.task_id
         WHERE mr.referenced_task_id = ?
           AND t.id != ?
        """,
        (task_id, task_id),
    ).fetchall():
        related[r["task_id"]] = {
            "task_id": r["task_id"],
            "via": "reference",
            "current_state": r["current_state"],
            "error_code": r["error_code"],
            "updated_at": r["updated_at"],
        }

    if root["context_id"] and root["terminal_at"]:
        root_terminal = _parse_iso(root["terminal_at"])
        if root_terminal is not None:
            window_end = (root_terminal + timedelta(seconds=window_seconds)).isoformat()
            for r in conn.execute(
                """
                SELECT id, current_state, error_code, updated_at, terminal_at
                  FROM tasks
                 WHERE context_id = ?
                   AND id != ?
                   AND current_state IN ('failed','rejected','canceled')
                   AND terminal_at >= ?
                   AND terminal_at <= ?
                """,
                (root["context_id"], task_id, root["terminal_at"], window_end),
            ).fetchall():
                if r["id"] in related:
                    related[r["id"]]["via"] = "reference+context"
                else:
                    related[r["id"]] = {
                        "task_id": r["id"],
                        "via": "context",
                        "current_state": r["current_state"],
                        "error_code": r["error_code"],
                        "updated_at": r["updated_at"],
                    }
    return list(related.values())
