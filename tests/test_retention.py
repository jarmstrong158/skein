"""Tests for retention / cleanup."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from skein.ingest.normalizer import store
from skein.ingest.parser import parse
from skein.retention import clean_older_than, parse_duration
from tests.conftest import load_fixture


def test_parse_duration_accepts_dhm():
    assert parse_duration("7d") == timedelta(days=7)
    assert parse_duration("12h") == timedelta(hours=12)
    assert parse_duration("30m") == timedelta(minutes=30)


def test_parse_duration_rejects_garbage():
    with pytest.raises(ValueError):
        parse_duration("forever")


def test_clean_only_removes_terminal_tasks_past_cutoff(db):
    # Seed: one completed task (terminal), one stuck task (non-terminal).
    store(db, parse(load_fixture("01_message_send_request.json")), direction="outbound")
    store(db, parse(load_fixture("03_task_completed.json")), direction="inbound")
    store(db, parse(load_fixture("04_followup_with_reference.json")), direction="outbound")
    # Backdate everything so it's "old".
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    db.execute("UPDATE tasks SET created_at = ?, updated_at = ?, terminal_at = NULL", (old, old))
    db.execute("UPDATE tasks SET terminal_at = ? WHERE id = 'task-abc'", (old,))

    result = clean_older_than(db, older_than=timedelta(days=7))

    # task-abc was terminal and old: deleted.
    # task-def was non-terminal: kept.
    assert result.tasks_deleted == 1
    remaining = {r["id"] for r in db.execute("SELECT id FROM tasks").fetchall()}
    assert "task-abc" not in remaining
    assert "task-def" in remaining


def test_clean_keeps_recent_terminal_tasks(db):
    store(db, parse(load_fixture("01_message_send_request.json")), direction="outbound")
    store(db, parse(load_fixture("03_task_completed.json")), direction="inbound")
    # Recent terminal task: keep.
    result = clean_older_than(db, older_than=timedelta(days=7))
    assert result.tasks_deleted == 0


def test_clean_cascades_to_messages_and_warnings(db):
    bad = {
        "jsonrpc": "1.0", "id": 1, "method": "message/send",
        "params": {"message": {"taskId": "t-bad", "contextId": "c"}},
    }
    store(db, parse(bad), direction="outbound")
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    db.execute("UPDATE tasks SET updated_at = ?, terminal_at = ?, current_state = 'failed'", (old, old))

    result = clean_older_than(db, older_than=timedelta(days=7))
    assert result.tasks_deleted == 1
    assert result.messages_deleted >= 1
    assert result.warnings_deleted >= 1
    assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM spec_warnings").fetchone()[0] == 0
