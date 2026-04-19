"""Tests for OTLP / W3C trace context extraction."""

from __future__ import annotations

from skein.ingest.normalizer import store
from skein.ingest.parser import _parse_traceparent, parse

TP = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_ID = "00f067aa0ba902b7"


def test_parse_traceparent_extracts_trace_and_span():
    tid, sid = _parse_traceparent(TP)
    assert tid == TRACE_ID
    assert sid == SPAN_ID


def test_parse_traceparent_rejects_malformed():
    assert _parse_traceparent("garbage") == (None, None)
    assert _parse_traceparent("00-short-short-01") == (None, None)
    assert _parse_traceparent("") == (None, None)


def test_parse_extracts_trace_id_from_message_metadata():
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {
            "message": {
                "messageId": "m1", "role": "user", "parts": [{"kind": "text", "text": "hi"}],
                "taskId": "t-meta", "contextId": "c-meta",
                "metadata": {"traceparent": TP},
            },
        },
    }
    event = parse(payload)
    assert event.message.trace_id == TRACE_ID
    assert event.message.span_id == SPAN_ID
    assert event.message.traceparent == TP


def test_parse_extracts_split_trace_id_from_metadata():
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {
            "message": {
                "messageId": "m1", "role": "user", "parts": [{"kind": "text", "text": "hi"}],
                "taskId": "t-split", "contextId": "c-split",
                "metadata": {"trace_id": TRACE_ID, "span_id": SPAN_ID},
            },
        },
    }
    event = parse(payload)
    assert event.message.trace_id == TRACE_ID
    assert event.message.span_id == SPAN_ID
    assert event.message.traceparent is None  # not provided in this shape


def test_parse_extracts_trace_id_from_result_metadata():
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "result": {
            "id": "t-result", "contextId": "c", "status": {"state": "completed"},
            "metadata": {"traceparent": TP},
        },
    }
    event = parse(payload)
    assert event.message.trace_id == TRACE_ID


def test_normalizer_persists_trace_id(db):
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {
            "message": {
                "messageId": "m1", "role": "user", "parts": [{"kind": "text", "text": "hi"}],
                "taskId": "t-persist", "contextId": "c",
                "metadata": {"traceparent": TP},
            },
        },
    }
    store(db, parse(payload), direction="outbound")
    row = db.execute(
        "SELECT trace_id, span_id, traceparent FROM messages WHERE task_id = 't-persist'"
    ).fetchone()
    assert row["trace_id"] == TRACE_ID
    assert row["span_id"] == SPAN_ID
    assert row["traceparent"] == TP


def test_route_honors_top_level_traceparent_when_payload_lacks_metadata(client, db):
    # Payload without metadata...
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {
            "messageId": "m1", "role": "user", "parts": [{"kind": "text", "text": "hi"}],
            "taskId": "t-route", "contextId": "c",
        }},
    }
    # ...but caller forwards traceparent at the body's top level.
    r = client.post("/trace/ingest", json={
        "payload": payload, "direction": "outbound", "traceparent": TP,
    })
    assert r.status_code == 201
    row = db.execute(
        "SELECT trace_id, traceparent FROM messages WHERE task_id = 't-route'"
    ).fetchone()
    assert row["trace_id"] == TRACE_ID
    assert row["traceparent"] == TP
