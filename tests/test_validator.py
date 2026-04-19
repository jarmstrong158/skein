"""Tests for the passive A2A spec validator."""

from __future__ import annotations

from skein.ingest.normalizer import store, upsert_agent_card
from skein.ingest.parser import parse
from skein.validator import validate_agent_card, validate_payload
from tests.conftest import load_fixture


# ---------- pure validator ----------

def test_validate_payload_clean_returns_no_warnings():
    payload = load_fixture("01_message_send_request.json")
    assert validate_payload(payload) == []


def test_validate_payload_flags_wrong_jsonrpc_version():
    bad = {"jsonrpc": "1.0", "id": 1, "method": "x", "params": {}}
    warnings = validate_payload(bad)
    assert any(w.code == "jsonrpc/wrong-version" for w in warnings)


def test_validate_payload_flags_invalid_task_state():
    bad = {
        "jsonrpc": "2.0", "id": 1,
        "result": {"id": "t1", "status": {"state": "halted"}},
    }
    warnings = validate_payload(bad)
    assert any(w.code == "a2a/invalid-task-state" for w in warnings)


def test_validate_payload_flags_message_missing_required_fields():
    bad = {
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {"taskId": "t", "contextId": "c"}},  # missing id, role, parts
    }
    codes = {w.code for w in validate_payload(bad)}
    assert "a2a/message-missing-id" in codes
    assert "a2a/message-missing-role" in codes
    assert "a2a/message-missing-parts" in codes


def test_validate_agent_card_flags_missing_fields():
    bad = {"name": "x"}  # missing url + version
    codes = {w.code for w in validate_agent_card(bad)}
    assert "a2a/agent-card-missing-required-field" in codes
    # And we should get one warning per missing field (url, version)
    warnings = validate_agent_card(bad)
    assert sum(1 for w in warnings if w.code == "a2a/agent-card-missing-required-field") == 2


# ---------- end-to-end via normalizer ----------

def test_normalizer_writes_spec_warnings_on_bad_payload(db):
    bad = {
        "jsonrpc": "1.0", "id": 1, "method": "message/send",
        "params": {"message": {"taskId": "tx", "contextId": "cx"}},
    }
    store(db, parse(bad), direction="outbound")
    rows = db.execute(
        "SELECT code, severity FROM spec_warnings WHERE task_id = 'tx' ORDER BY id"
    ).fetchall()
    codes = {r["code"] for r in rows}
    assert "jsonrpc/wrong-version" in codes
    assert "a2a/message-missing-parts" in codes


def test_normalizer_writes_no_warnings_on_clean_payload(db):
    payload = load_fixture("01_message_send_request.json")
    store(db, parse(payload), direction="outbound")
    n = db.execute("SELECT COUNT(*) AS c FROM spec_warnings").fetchone()["c"]
    assert n == 0


def test_agent_card_with_missing_fields_produces_warnings(db):
    upsert_agent_card(db, {"name": "X"})  # missing url + version
    n = db.execute(
        "SELECT COUNT(*) AS c FROM spec_warnings WHERE agent_id = 'X'"
    ).fetchone()["c"]
    assert n >= 2
