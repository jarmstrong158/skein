"""Build an ordered timeline of events for a given task.

A "timeline" is a chronological merge of:
- messages (with their JSON-RPC payload, direction, agents)
- state transitions
- artifacts produced

Ordering rule: by best-known timestamp (occurred_at if asserted, else
captured_at), with sequence number as a stable tie-breaker for messages.
This handles out-of-order arrival without losing the canonical sequence.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Any, Literal


EventKind = Literal["message", "state_transition", "artifact"]


@dataclass
class TimelineEvent:
    kind: EventKind
    at: str
    sort_key: tuple
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Timeline:
    task_id: str
    task: dict[str, Any] | None
    events: list[TimelineEvent]
    referenced_task_ids: list[str]


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def build(conn: sqlite3.Connection, task_id: str) -> Timeline | None:
    """Build a Timeline for a task. Returns None if the task does not exist."""
    task_row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if task_row is None:
        return None
    task = _row_to_dict(task_row)

    events: list[TimelineEvent] = []

    msg_rows = conn.execute(
        """
        SELECT id, sequence, direction, method, from_agent_id, to_agent_id,
               payload_json, protocol_version, captured_at, occurred_at
          FROM messages
         WHERE task_id = ?
         ORDER BY sequence
        """,
        (task_id,),
    ).fetchall()

    # Per-message references
    if msg_rows:
        msg_ids = [r["id"] for r in msg_rows]
        placeholders = ",".join("?" for _ in msg_ids)
        ref_rows = conn.execute(
            f"SELECT message_id, referenced_task_id FROM message_references WHERE message_id IN ({placeholders})",
            msg_ids,
        ).fetchall()
        refs_by_msg: dict[int, list[str]] = {}
        for r in ref_rows:
            refs_by_msg.setdefault(r["message_id"], []).append(r["referenced_task_id"])
    else:
        refs_by_msg = {}

    for r in msg_rows:
        at = r["occurred_at"] or r["captured_at"]
        try:
            payload = json.loads(r["payload_json"])
        except (TypeError, ValueError):
            payload = None
        events.append(
            TimelineEvent(
                kind="message",
                at=at,
                sort_key=(at, 0, r["sequence"]),
                data={
                    "message_id": r["id"],
                    "sequence": r["sequence"],
                    "direction": r["direction"],
                    "method": r["method"],
                    "from_agent_id": r["from_agent_id"],
                    "to_agent_id": r["to_agent_id"],
                    "protocol_version": r["protocol_version"],
                    "payload": payload,
                    "captured_at": r["captured_at"],
                    "occurred_at": r["occurred_at"],
                    "references": refs_by_msg.get(r["id"], []),
                },
            )
        )

    for r in conn.execute(
        """
        SELECT id, from_state, to_state, at, triggered_by_message_id
          FROM state_transitions
         WHERE task_id = ?
         ORDER BY id
        """,
        (task_id,),
    ).fetchall():
        events.append(
            TimelineEvent(
                kind="state_transition",
                at=r["at"],
                sort_key=(r["at"], 1, r["id"]),
                data={
                    "from_state": r["from_state"],
                    "to_state": r["to_state"],
                    "triggered_by_message_id": r["triggered_by_message_id"],
                },
            )
        )

    for r in conn.execute(
        """
        SELECT id, name, mime_type, content_text, bytes, produced_at
          FROM artifacts
         WHERE task_id = ?
         ORDER BY id
        """,
        (task_id,),
    ).fetchall():
        events.append(
            TimelineEvent(
                kind="artifact",
                at=r["produced_at"],
                sort_key=(r["produced_at"], 2, r["id"]),
                data={
                    "name": r["name"],
                    "mime_type": r["mime_type"],
                    "content_text": r["content_text"],
                    "bytes": r["bytes"],
                },
            )
        )

    events.sort(key=lambda e: e.sort_key)

    referenced: list[str] = []
    seen: set[str] = set()
    for e in events:
        if e.kind == "message":
            for ref in e.data.get("references", []):
                if ref not in seen:
                    seen.add(ref)
                    referenced.append(ref)

    return Timeline(
        task_id=task_id,
        task=task,
        events=events,
        referenced_task_ids=referenced,
    )


def to_dict(timeline: Timeline) -> dict[str, Any]:
    return {
        "task_id": timeline.task_id,
        "task": timeline.task,
        "referenced_task_ids": timeline.referenced_task_ids,
        "events": [
            {"kind": e.kind, "at": e.at, **e.data} for e in timeline.events
        ],
    }
