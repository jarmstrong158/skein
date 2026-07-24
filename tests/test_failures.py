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


def _insert_task(db, task_id, *, state, context_id, terminal_at=None, at=None):
    at = at or datetime.now(timezone.utc).isoformat()
    db.execute(
        """
        INSERT INTO tasks (id, context_id, current_state, created_at, updated_at, terminal_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (task_id, context_id, state, at, at, terminal_at),
    )


def _insert_reference(db, *, from_task, to_task, at=None):
    """Give `from_task` a message that names `to_task` in referenceTaskIds."""
    at = at or datetime.now(timezone.utc).isoformat()
    cur = db.execute(
        """
        INSERT INTO messages (task_id, sequence, direction, method,
                              payload_json, payload_hash, captured_at)
        VALUES (?, 1, 'outbound', 'message/send', '{}', ?, ?)
        """,
        (from_task, f"hash-{from_task}", at),
    )
    db.execute(
        "INSERT INTO message_references (message_id, referenced_task_id) VALUES (?, ?)",
        (cur.lastrowid, to_task),
    )


def test_cascade_context_signal_finds_sibling_failure_in_window(db):
    """Signal 2: same contextId, failed inside the window, no reference edge."""
    root_at = datetime.now(timezone.utc)
    _insert_task(db, "t-root", state="failed", context_id="ctx-1",
                 terminal_at=root_at.isoformat())
    sibling_at = (root_at + timedelta(seconds=120)).isoformat()
    _insert_task(db, "t-sibling", state="failed", context_id="ctx-1",
                 terminal_at=sibling_at)

    cascade = cascade_for(db, "t-root")
    assert len(cascade) == 1
    assert cascade[0]["task_id"] == "t-sibling"
    assert cascade[0]["via"] == "context"


def test_cascade_context_signal_ignores_failure_outside_window(db):
    root_at = datetime.now(timezone.utc)
    _insert_task(db, "t-root", state="failed", context_id="ctx-1",
                 terminal_at=root_at.isoformat())
    late = (root_at + timedelta(seconds=900)).isoformat()
    _insert_task(db, "t-late", state="failed", context_id="ctx-1", terminal_at=late)

    assert cascade_for(db, "t-root", window_seconds=300) == []


def test_cascade_marks_task_hit_by_both_signals_as_reference_plus_context(db):
    root_at = datetime.now(timezone.utc)
    _insert_task(db, "t-root", state="failed", context_id="ctx-1",
                 terminal_at=root_at.isoformat())
    both_at = (root_at + timedelta(seconds=60)).isoformat()
    _insert_task(db, "t-both", state="failed", context_id="ctx-1", terminal_at=both_at)
    _insert_reference(db, from_task="t-both", to_task="t-root")

    cascade = cascade_for(db, "t-root")
    assert [c["via"] for c in cascade] == ["reference+context"]


# ---------- cascade ordering constraint (signal 1) ----------

def test_cascade_excludes_task_that_finished_before_the_failure(db):
    """A task that referenced the root an hour *before* it failed is not affected.

    Ordering matters: if the referencing task was already terminal when the
    root failed, the root's failure cannot have caused anything in it.
    """
    root_at = datetime.now(timezone.utc)
    _insert_task(db, "t-root", state="failed", context_id="ctx-1",
                 terminal_at=root_at.isoformat())
    long_before = (root_at - timedelta(hours=1)).isoformat()
    _insert_task(db, "t-earlier", state="completed", context_id="ctx-1",
                 terminal_at=long_before, at=long_before)
    _insert_reference(db, from_task="t-earlier", to_task="t-root", at=long_before)

    assert cascade_for(db, "t-root") == []


def test_cascade_includes_referencing_task_still_running_when_root_failed(db):
    """Still non-terminal at failure time — genuinely may be affected."""
    root_at = datetime.now(timezone.utc)
    _insert_task(db, "t-root", state="failed", context_id="ctx-1",
                 terminal_at=root_at.isoformat())
    _insert_task(db, "t-live", state="working", context_id="ctx-1", terminal_at=None)
    _insert_reference(db, from_task="t-live", to_task="t-root")

    cascade = cascade_for(db, "t-root")
    assert [c["task_id"] for c in cascade] == ["t-live"]
    assert cascade[0]["via"] == "reference"


def test_cascade_includes_referencing_task_that_finished_after_the_failure(db):
    """Terminal after the root failed, and non-failed — still lineage-relevant."""
    root_at = datetime.now(timezone.utc)
    _insert_task(db, "t-root", state="failed", context_id="ctx-1",
                 terminal_at=root_at.isoformat())
    after = (root_at + timedelta(seconds=30)).isoformat()
    _insert_task(db, "t-after", state="completed", context_id="ctx-1", terminal_at=after)
    _insert_reference(db, from_task="t-after", to_task="t-root")

    cascade = cascade_for(db, "t-root")
    assert [c["task_id"] for c in cascade] == ["t-after"]
    assert cascade[0]["via"] == "reference"


def test_cascade_without_root_terminal_at_applies_no_ordering_filter(db):
    """No terminal_at on the root means no instant to order against."""
    _insert_task(db, "t-root", state="working", context_id="ctx-1", terminal_at=None)
    long_before = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    _insert_task(db, "t-earlier", state="completed", context_id="ctx-1",
                 terminal_at=long_before, at=long_before)
    _insert_reference(db, from_task="t-earlier", to_task="t-root", at=long_before)

    assert [c["task_id"] for c in cascade_for(db, "t-root")] == ["t-earlier"]
