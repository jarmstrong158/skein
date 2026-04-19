"""Tests for failure detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from skein.failures.detector import (
    TIMEOUT_ERROR_CODE,
    cascade_for,
    failure_patterns,
    recent_failures,
    sweep_stale_tasks,
)
from skein.ingest.normalizer import store
from skein.ingest.parser import parse
from tests.conftest import load_fixture


def _ingest(db, fixture, direction="inbound"):
    store(db, parse(load_fixture(fixture)), direction=direction)


# ---------- sweep_stale_tasks ----------

def test_sweep_marks_old_non_terminal_tasks_failed(db):
    _ingest(db, "01_message_send_request.json", direction="outbound")
    # Backdate the task so it appears stale.
    old = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    db.execute("UPDATE tasks SET created_at = ?, updated_at = ?", (old, old))

    result = sweep_stale_tasks(db, default_timeout_seconds=300)
    assert result.marked_failed == ["task-abc"]

    row = db.execute("SELECT current_state, error_code, terminal_at FROM tasks WHERE id = ?", ("task-abc",)).fetchone()
    assert row["current_state"] == "failed"
    assert row["error_code"] == TIMEOUT_ERROR_CODE
    assert row["terminal_at"] is not None


def test_sweep_skips_terminal_tasks(db):
    _ingest(db, "01_message_send_request.json", direction="outbound")
    _ingest(db, "03_task_completed.json")
    old = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    db.execute("UPDATE tasks SET updated_at = ?", (old,))

    result = sweep_stale_tasks(db, default_timeout_seconds=300)
    assert result.marked_failed == []  # task-abc is completed, terminal_at set


def test_sweep_respects_per_task_timeout_override(db):
    _ingest(db, "01_message_send_request.json", direction="outbound")
    # 60s ago — would be stale at default 30s but not at per-task 120s
    sixty_sec_ago = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    db.execute(
        "UPDATE tasks SET updated_at = ?, timeout_seconds = ?",
        (sixty_sec_ago, 120),
    )
    result = sweep_stale_tasks(db, default_timeout_seconds=30)
    assert result.marked_failed == []


# ---------- recent_failures / failure_patterns ----------

def test_recent_failures_returns_failed_tasks(db):
    _ingest(db, "04_followup_with_reference.json", direction="outbound")
    _ingest(db, "05_task_failed.json")
    failures = recent_failures(db, hours=24)
    assert any(f["id"] == "task-def" for f in failures)


def test_failure_patterns_groups_by_error_code(db):
    _ingest(db, "04_followup_with_reference.json", direction="outbound")
    _ingest(db, "05_task_failed.json")
    patterns = failure_patterns(db, days=7)
    codes = {p["error_code"] for p in patterns}
    assert "-32001" in codes
    pattern = next(p for p in patterns if p["error_code"] == "-32001")
    assert pattern["count"] == 1
    assert "task-def" in pattern["example_task_ids"]


# ---------- cascade_for ----------

def test_cascade_finds_tasks_referencing_the_failed_one(db):
    _ingest(db, "01_message_send_request.json", direction="outbound")
    _ingest(db, "03_task_completed.json")
    _ingest(db, "04_followup_with_reference.json", direction="outbound")
    _ingest(db, "05_task_failed.json")

    # task-def references task-abc; mark task-abc terminal so cascade query has anchor
    cascade = cascade_for(db, "task-abc")
    via_ref = [c for c in cascade if c["task_id"] == "task-def"]
    assert via_ref, "expected task-def to appear in cascade for task-abc"
    assert via_ref[0]["via"] in ("reference", "reference+context")


def test_cascade_returns_empty_for_unknown_task(db):
    assert cascade_for(db, "nope") == []
