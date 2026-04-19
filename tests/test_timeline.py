"""Unit tests for timeline builder."""

from __future__ import annotations

from skein.ingest.normalizer import store
from skein.ingest.parser import parse
from skein.timeline.builder import build, to_dict
from tests.conftest import load_fixture


def _ingest(db, fixture_name, direction="inbound"):
    payload = load_fixture(fixture_name)
    event = parse(payload, protocol_version="0.3.1")
    return store(db, event, direction=direction)


def test_build_returns_none_for_unknown_task(db):
    assert build(db, "nope") is None


def test_build_orders_events_chronologically(db):
    _ingest(db, "01_message_send_request.json", direction="outbound")
    _ingest(db, "02_status_working.json")
    _ingest(db, "03_task_completed.json")

    tl = build(db, "task-abc")
    assert tl is not None
    assert tl.task["current_state"] == "completed"

    # Expect: 3 messages, 3 state transitions (None→submitted, submitted→working,
    # working→completed), 1 artifact = 7 events.
    assert len(tl.events) == 7

    kinds = [e.kind for e in tl.events]
    assert kinds.count("message") == 3
    assert kinds.count("state_transition") == 3
    assert kinds.count("artifact") == 1

    # Timestamps should be non-decreasing
    times = [e.at for e in tl.events]
    assert times == sorted(times)


def test_build_includes_referenced_task_ids(db):
    _ingest(db, "01_message_send_request.json", direction="outbound")
    _ingest(db, "04_followup_with_reference.json", direction="outbound")
    tl = build(db, "task-def")
    assert "task-abc" in tl.referenced_task_ids


def test_to_dict_is_json_safe(db):
    import json
    _ingest(db, "01_message_send_request.json", direction="outbound")
    _ingest(db, "03_task_completed.json")
    tl = build(db, "task-abc")
    blob = to_dict(tl)
    json.dumps(blob)  # must not raise
    assert blob["task_id"] == "task-abc"
    assert any(e["kind"] == "artifact" for e in blob["events"])
