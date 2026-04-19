"""Retention / cleanup of old trace data.

Pure SQL helpers used by `skein clean` and (optionally) by an APScheduler
job. Deletes are scoped to terminal tasks older than a cutoff so we never
remove in-flight work.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_DURATION_RE = re.compile(r"^\s*(\d+)\s*([dhm])\s*$", re.IGNORECASE)


def parse_duration(s: str) -> timedelta:
    """Parse a duration like '7d', '12h', '30m'. Raises ValueError otherwise."""
    m = _DURATION_RE.match(s)
    if not m:
        raise ValueError(f"unrecognized duration {s!r}; expected formats like '7d', '12h', '30m'")
    n, unit = int(m.group(1)), m.group(2).lower()
    return {
        "d": timedelta(days=n),
        "h": timedelta(hours=n),
        "m": timedelta(minutes=n),
    }[unit]


@dataclass
class CleanResult:
    cutoff_iso: str
    tasks_deleted: int
    messages_deleted: int
    transitions_deleted: int
    artifacts_deleted: int
    refs_deleted: int
    warnings_deleted: int


def clean_older_than(
    conn: sqlite3.Connection, *, older_than: timedelta, now: datetime | None = None
) -> CleanResult:
    """Delete data for terminal tasks whose updated_at is older than the cutoff.

    Children (messages, transitions, artifacts, refs, warnings) are deleted
    explicitly because the schema declares foreign keys but SQLite is permissive
    by default. Single transaction.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = (now - older_than).isoformat()

    conn.execute("BEGIN")
    try:
        target_ids = [
            r["id"]
            for r in conn.execute(
                """
                SELECT id FROM tasks
                 WHERE terminal_at IS NOT NULL
                   AND updated_at < ?
                """,
                (cutoff,),
            ).fetchall()
        ]
        if not target_ids:
            conn.execute("COMMIT")
            return CleanResult(cutoff, 0, 0, 0, 0, 0, 0)

        placeholders = ",".join("?" for _ in target_ids)

        msg_ids = [
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM messages WHERE task_id IN ({placeholders})",
                target_ids,
            ).fetchall()
        ]
        refs_deleted = 0
        if msg_ids:
            mph = ",".join("?" for _ in msg_ids)
            refs_deleted = conn.execute(
                f"DELETE FROM message_references WHERE message_id IN ({mph})",
                msg_ids,
            ).rowcount or 0

        warnings_deleted = conn.execute(
            f"DELETE FROM spec_warnings WHERE task_id IN ({placeholders})",
            target_ids,
        ).rowcount or 0
        artifacts_deleted = conn.execute(
            f"DELETE FROM artifacts WHERE task_id IN ({placeholders})",
            target_ids,
        ).rowcount or 0
        transitions_deleted = conn.execute(
            f"DELETE FROM state_transitions WHERE task_id IN ({placeholders})",
            target_ids,
        ).rowcount or 0
        messages_deleted = conn.execute(
            f"DELETE FROM messages WHERE task_id IN ({placeholders})",
            target_ids,
        ).rowcount or 0
        tasks_deleted = conn.execute(
            f"DELETE FROM tasks WHERE id IN ({placeholders})", target_ids,
        ).rowcount or 0

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return CleanResult(
        cutoff_iso=cutoff,
        tasks_deleted=tasks_deleted,
        messages_deleted=messages_deleted,
        transitions_deleted=transitions_deleted,
        artifacts_deleted=artifacts_deleted,
        refs_deleted=refs_deleted,
        warnings_deleted=warnings_deleted,
    )
