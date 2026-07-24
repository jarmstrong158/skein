"""Persist a ParsedEvent into the SQLite store.

All writes happen in a single transaction per ingest call.
Idempotent on (task_id, payload_hash).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..states import SUBMITTED, is_terminal_state
from ..validator import validate_agent_card, validate_payload
from .parser import ParsedEvent, payload_hash


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _upsert_task(conn: sqlite3.Connection, event: ParsedEvent, captured_at: str) -> None:
    task = event.task
    if task is None or not task.id:
        return
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task.id,)).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO tasks (
                id, context_id, current_state, created_at, updated_at,
                terminal_at, error_code, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.id,
                task.context_id,
                task.state or SUBMITTED,
                captured_at,
                captured_at,
                captured_at if is_terminal_state(task.state) else None,
                task.error_code,
                task.error_message,
            ),
        )
    else:
        new_state = task.state or row["current_state"]
        terminal_at = row["terminal_at"]
        if terminal_at is None and is_terminal_state(new_state):
            terminal_at = captured_at
        conn.execute(
            """
            UPDATE tasks
               SET context_id    = COALESCE(?, context_id),
                   current_state = ?,
                   updated_at    = ?,
                   terminal_at   = ?,
                   error_code    = COALESCE(?, error_code),
                   error_message = COALESCE(?, error_message)
             WHERE id = ?
            """,
            (
                task.context_id,
                new_state,
                captured_at,
                terminal_at,
                task.error_code,
                task.error_message,
                task.id,
            ),
        )


def _upsert_agent_stub(conn: sqlite3.Connection, agent_id: str | None, captured_at: str) -> None:
    """Create a minimal agents row for an unknown agent_id seen in a message.
    Full card data arrives via /trace/agent_card.
    """
    if not agent_id:
        return
    row = conn.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if row is None:
        conn.execute(
            """
            INSERT INTO agents (id, first_seen_at, last_seen_at)
            VALUES (?, ?, ?)
            """,
            (agent_id, captured_at, captured_at),
        )
    else:
        conn.execute(
            "UPDATE agents SET last_seen_at = ? WHERE id = ?",
            (captured_at, agent_id),
        )


def _next_sequence(conn: sqlite3.Connection, task_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) AS s FROM messages WHERE task_id = ?",
        (task_id,),
    ).fetchone()
    return int(row["s"]) + 1


def _record_state_transition(
    conn: sqlite3.Connection,
    task_id: str,
    prev_state: str | None,
    new_state: str | None,
    at: str,
    message_id: int | None,
) -> None:
    if not new_state or new_state == prev_state:
        return
    conn.execute(
        """
        INSERT INTO state_transitions (task_id, from_state, to_state, at, triggered_by_message_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (task_id, prev_state, new_state, at, message_id),
    )


def store(
    conn: sqlite3.Connection,
    event: ParsedEvent,
    *,
    direction: str,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Persist a parsed event. Returns {message_id, task_id, sequence, deduped}.

    Direction: 'inbound' or 'outbound' relative to the capturing agent.
    """
    if direction not in ("inbound", "outbound"):
        raise ValueError(f"direction must be inbound|outbound, got {direction!r}")

    captured_at = captured_at or _now_iso()
    task = event.task
    msg = event.message

    if task is None or not task.id:
        # No task identity — we can't store a message without a task in v1 schema.
        raise ValueError("payload has no extractable taskId; cannot ingest")

    h = payload_hash(msg.payload)

    # Begin transaction. SQLite isolation_level=None means we manage explicitly.
    conn.execute("BEGIN")
    try:
        # Capture prior state for transition recording
        prior = conn.execute(
            "SELECT current_state FROM tasks WHERE id = ?", (task.id,)
        ).fetchone()
        prior_state = prior["current_state"] if prior else None

        # Idempotency check
        existing = conn.execute(
            "SELECT id, sequence FROM messages WHERE task_id = ? AND payload_hash = ?",
            (task.id, h),
        ).fetchone()
        if existing is not None:
            conn.execute("COMMIT")
            return {
                "message_id": existing["id"],
                "task_id": task.id,
                "sequence": existing["sequence"],
                "deduped": True,
            }

        _upsert_agent_stub(conn, msg.from_agent_id, captured_at)
        _upsert_agent_stub(conn, msg.to_agent_id, captured_at)
        _upsert_task(conn, event, captured_at)

        seq = _next_sequence(conn, task.id)
        cur = conn.execute(
            """
            INSERT INTO messages (
                task_id, sequence, direction, method, from_agent_id, to_agent_id,
                payload_json, payload_hash, protocol_version, extra_json,
                captured_at, occurred_at,
                trace_id, span_id, traceparent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.id,
                seq,
                direction,
                msg.method,
                msg.from_agent_id,
                msg.to_agent_id,
                json.dumps(msg.payload, sort_keys=True),
                h,
                event.protocol_version,
                json.dumps(msg.extra, sort_keys=True) if msg.extra else None,
                captured_at,
                msg.occurred_at,
                msg.trace_id,
                msg.span_id,
                msg.traceparent,
            ),
        )
        message_id = cur.lastrowid

        for ref in msg.reference_task_ids:
            conn.execute(
                "INSERT OR IGNORE INTO message_references (message_id, referenced_task_id) VALUES (?, ?)",
                (message_id, ref),
            )

        for w in validate_payload(msg.payload):
            conn.execute(
                """
                INSERT INTO spec_warnings (task_id, message_id, severity, code, description, field_path, raised_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task.id, message_id, w.severity, w.code, w.description, w.field_path, captured_at),
            )

        # Prefer the agent's own assertion of *when the state changed*
        # (A2A `status.timestamp`) over the message time, and that over our
        # capture time. This is where ParsedTask.state_timestamp lands.
        new_state = task.state
        transition_at = task.state_timestamp or msg.occurred_at or captured_at
        _record_state_transition(
            conn, task.id, prior_state, new_state, transition_at, message_id
        )

        for art in event.artifacts:
            conn.execute(
                """
                INSERT INTO artifacts (task_id, name, mime_type, content_text, content_path, bytes, produced_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    art.name,
                    art.mime_type,
                    art.content_text,
                    None,
                    art.bytes,
                    art.produced_at or captured_at,
                ),
            )

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return {
        "message_id": message_id,
        "task_id": task.id,
        "sequence": seq,
        "deduped": False,
    }


def upsert_agent_card(
    conn: sqlite3.Connection, card: dict[str, Any], captured_at: str | None = None
) -> str:
    """Store a full agent card. Returns the agent id."""
    captured_at = captured_at or _now_iso()
    agent_id = card.get("url") or card.get("id") or card.get("name")
    if not agent_id:
        raise ValueError("agent card has no identifying field (url/id/name)")
    row = conn.execute("SELECT first_seen_at FROM agents WHERE id = ?", (agent_id,)).fetchone()
    card_json = json.dumps(card, sort_keys=True)
    if row is None:
        conn.execute(
            """
            INSERT INTO agents (id, name, endpoint_url, card_json, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (agent_id, card.get("name"), card.get("url"), card_json, captured_at, captured_at),
        )
    else:
        conn.execute(
            """
            UPDATE agents
               SET name         = COALESCE(?, name),
                   endpoint_url = COALESCE(?, endpoint_url),
                   card_json    = ?,
                   last_seen_at = ?
             WHERE id = ?
            """,
            (card.get("name"), card.get("url"), card_json, captured_at, agent_id),
        )
    for w in validate_agent_card(card):
        conn.execute(
            """
            INSERT INTO spec_warnings (task_id, message_id, agent_id, severity, code, description, field_path, raised_at)
            VALUES (NULL, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (agent_id, w.severity, w.code, w.description, w.field_path, captured_at),
        )
    return agent_id
