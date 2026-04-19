"""Integration tests for ingest endpoints + storage."""

from __future__ import annotations

from tests.conftest import load_fixture


def _post_ingest(client, payload, direction="inbound"):
    return client.post(
        "/trace/ingest",
        json={"payload": payload, "direction": direction, "protocol_version": "0.3.1"},
    )


def test_health_endpoint(client):
    r = client.get("/trace/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_ingest_full_flow_creates_task_messages_and_artifacts(client, db):
    """End-to-end: send → working → completed across 3 ingests on one task."""
    for fname in ("01_message_send_request.json",
                  "02_status_working.json",
                  "03_task_completed.json"):
        r = _post_ingest(client, load_fixture(fname))
        assert r.status_code == 201, r.get_json()
        body = r.get_json()
        assert body["task_id"] == "task-abc"
        assert body["deduped"] is False

    task = db.execute("SELECT * FROM tasks WHERE id = ?", ("task-abc",)).fetchone()
    assert task["current_state"] == "completed"
    assert task["context_id"] == "ctx-001"
    assert task["terminal_at"] is not None

    msgs = db.execute(
        "SELECT * FROM messages WHERE task_id = ? ORDER BY sequence", ("task-abc",)
    ).fetchall()
    assert [m["sequence"] for m in msgs] == [1, 2, 3]

    transitions = db.execute(
        "SELECT to_state FROM state_transitions WHERE task_id = ? ORDER BY id",
        ("task-abc",),
    ).fetchall()
    states = [t["to_state"] for t in transitions]
    assert "working" in states and "completed" in states

    arts = db.execute("SELECT * FROM artifacts WHERE task_id = ?", ("task-abc",)).fetchall()
    assert len(arts) == 1
    assert arts[0]["name"] == "summary"


def test_ingest_is_idempotent_on_duplicate_payload(client, db):
    payload = load_fixture("01_message_send_request.json")
    r1 = _post_ingest(client, payload)
    r2 = _post_ingest(client, payload)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.get_json()["deduped"] is False
    assert r2.get_json()["deduped"] is True
    assert r1.get_json()["message_id"] == r2.get_json()["message_id"]

    count = db.execute(
        "SELECT COUNT(*) AS c FROM messages WHERE task_id = ?", ("task-abc",)
    ).fetchone()["c"]
    assert count == 1


def test_ingest_records_reference_task_ids(client, db):
    _post_ingest(client, load_fixture("01_message_send_request.json"))
    _post_ingest(client, load_fixture("04_followup_with_reference.json"))
    refs = db.execute(
        """
        SELECT mr.referenced_task_id
          FROM message_references mr
          JOIN messages m ON m.id = mr.message_id
         WHERE m.task_id = ?
        """,
        ("task-def",),
    ).fetchall()
    assert [r["referenced_task_id"] for r in refs] == ["task-abc"]


def test_ingest_failed_task_captures_error(client, db):
    _post_ingest(client, load_fixture("04_followup_with_reference.json"))
    _post_ingest(client, load_fixture("05_task_failed.json"))
    task = db.execute("SELECT * FROM tasks WHERE id = ?", ("task-def",)).fetchone()
    assert task["current_state"] == "failed"
    assert task["error_code"] == "-32001"
    assert task["terminal_at"] is not None


def test_ingest_rejects_payload_without_taskid(client):
    bad = {"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {}}
    r = _post_ingest(client, bad)
    assert r.status_code == 400


def test_ingest_rejects_invalid_direction(client):
    payload = load_fixture("01_message_send_request.json")
    r = client.post("/trace/ingest", json={"payload": payload, "direction": "sideways"})
    assert r.status_code == 400


def test_agent_card_upsert(client, db):
    card = load_fixture("agent_card_analyst.json")
    r = client.post("/trace/agent_card", json=card)
    assert r.status_code == 201
    assert r.get_json()["agent_id"] == "https://analyst.example/agent"
    row = db.execute(
        "SELECT * FROM agents WHERE id = ?", ("https://analyst.example/agent",)
    ).fetchone()
    assert row["name"] == "Analyst Agent"
    assert "summarize_sales" in row["card_json"]


def test_agent_stub_created_for_unknown_agent_seen_in_message(client, db):
    _post_ingest(client, load_fixture("01_message_send_request.json"))
    rows = db.execute("SELECT id FROM agents ORDER BY id").fetchall()
    ids = {r["id"] for r in rows}
    assert "https://orchestrator.example/agent" in ids
    assert "https://analyst.example/agent" in ids
