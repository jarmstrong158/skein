"""Tests for the MCP tool functions (transport-agnostic)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from skein.ingest.normalizer import store, upsert_agent_card
from skein.ingest.parser import parse
from skein_mcp import tools as t
from tests.conftest import load_fixture


def _seed(db):
    for fname, direction in [
        ("01_message_send_request.json", "outbound"),
        ("02_status_working.json", "inbound"),
        ("03_task_completed.json", "inbound"),
        ("04_followup_with_reference.json", "outbound"),
        ("05_task_failed.json", "inbound"),
    ]:
        store(db, parse(load_fixture(fname)), direction=direction)
    upsert_agent_card(db, load_fixture("agent_card_analyst.json"))


def test_get_recent_failures(db):
    _seed(db)
    failures = t.get_recent_failures(db, hours=24)
    ids = {f["id"] for f in failures}
    assert "task-def" in ids
    assert "task-abc" not in ids  # completed, not failed


def test_get_task_timeline_returns_full_event_list(db):
    _seed(db)
    tl = t.get_task_timeline(db, "task-abc")
    assert tl is not None
    assert tl["task_id"] == "task-abc"
    kinds = {e["kind"] for e in tl["events"]}
    assert {"message", "state_transition", "artifact"} <= kinds


def test_get_task_timeline_returns_none_for_unknown(db):
    assert t.get_task_timeline(db, "nope") is None


def test_list_active_agents(db):
    _seed(db)
    agents = t.list_active_agents(db, since_minutes=60)
    ids = {a["id"] for a in agents}
    assert "https://analyst.example/agent" in ids
    # All seeded just-now, so all visible
    assert len(agents) >= 2


def test_get_agent_activity(db):
    _seed(db)
    activity = t.get_agent_activity(db, "https://analyst.example/agent", hours=24)
    assert activity["agent_id"] == "https://analyst.example/agent"
    assert activity["message_count"] >= 1
    assert "failure_rate" in activity
    assert 0.0 <= activity["failure_rate"] <= 1.0


def test_query_failure_patterns(db):
    _seed(db)
    patterns = t.query_failure_patterns(db, days=7)
    codes = {p["error_code"] for p in patterns}
    assert "-32001" in codes


def test_export_trace_includes_timeline_cascade_and_agents(db):
    _seed(db)
    blob = t.export_trace(db, "task-abc")
    assert blob is not None
    assert blob["task_id"] == "task-abc"
    assert "events" in blob and "cascade" in blob and "agents" in blob
    # Agents should include the analyst (seen in messages and registered as a card)
    agent_ids = {a["id"] for a in blob["agents"]}
    assert "https://analyst.example/agent" in agent_ids


def test_export_trace_can_omit_payloads(db):
    _seed(db)
    blob = t.export_trace(db, "task-abc", include_payloads=False)
    for e in blob["events"]:
        if e["kind"] == "message":
            assert "payload" not in e


def test_export_trace_returns_none_for_unknown(db):
    assert t.export_trace(db, "nope") is None
