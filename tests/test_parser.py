"""Unit tests for the A2A payload parser."""

from __future__ import annotations

import pytest

from skein.ingest.parser import ParseError, parse, payload_hash
from tests.conftest import load_fixture


def test_parse_message_send_request_extracts_task_and_context():
    payload = load_fixture("01_message_send_request.json")
    event = parse(payload)
    assert event.task is not None
    assert event.task.id == "task-abc"
    assert event.task.context_id == "ctx-001"
    assert event.message.method == "message/send"
    assert event.message.from_agent_id == "https://orchestrator.example/agent"
    assert event.message.to_agent_id == "https://analyst.example/agent"
    assert event.message.occurred_at == "2026-04-19T10:00:00Z"


def test_parse_status_update_event():
    payload = load_fixture("02_status_working.json")
    event = parse(payload)
    assert event.task is not None
    assert event.task.id == "task-abc"
    assert event.task.state == "working"
    assert event.task.state_timestamp == "2026-04-19T10:00:01Z"


def test_parse_completed_task_extracts_artifacts():
    payload = load_fixture("03_task_completed.json")
    event = parse(payload)
    assert event.task.state == "completed"
    assert len(event.artifacts) == 1
    assert event.artifacts[0].name == "summary"
    assert event.artifacts[0].mime_type == "text/plain"
    assert "Q1 sales" in event.artifacts[0].content_text


def test_parse_extracts_reference_task_ids():
    payload = load_fixture("04_followup_with_reference.json")
    event = parse(payload)
    assert event.message.reference_task_ids == ["task-abc"]
    assert event.task.id == "task-def"
    assert event.task.context_id == "ctx-001"


def test_parse_failed_task_captures_error():
    payload = load_fixture("05_task_failed.json")
    event = parse(payload)
    assert event.task.state == "failed"
    assert event.task.error_code == "-32001"
    assert "Historical data" in event.task.error_message


def test_parse_rejects_non_jsonrpc_payload():
    with pytest.raises(ParseError):
        parse({"not": "jsonrpc"})


def test_payload_hash_is_stable_under_key_reordering():
    a = {"jsonrpc": "2.0", "id": 1, "method": "x", "params": {"a": 1, "b": 2}}
    b = {"params": {"b": 2, "a": 1}, "method": "x", "id": 1, "jsonrpc": "2.0"}
    assert payload_hash(a) == payload_hash(b)
