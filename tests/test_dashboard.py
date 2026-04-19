"""Integration tests for dashboard pages."""

from __future__ import annotations

from skein.ingest.normalizer import store, upsert_agent_card
from skein.ingest.parser import parse
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


def test_overview_renders(client, db):
    _seed(db)
    r = client.get("/")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Skein" in body
    assert "Active tasks" in body
    assert "Failures (24h)" in body
    assert "task-abc" in body or "task-def" in body


def test_overview_htmx_partial(client, db):
    _seed(db)
    r = client.get("/", headers={"HX-Request": "true"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # Partial: no <html> wrapper
    assert "<html" not in body.lower()
    assert "stat-grid" in body


def test_agents_page_lists_agents(client, db):
    _seed(db)
    r = client.get("/agents")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Analyst Agent" in body
    assert "https://analyst.example/agent" in body


def test_tasks_page_lists_and_filters(client, db):
    _seed(db)
    r = client.get("/tasks")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "task-abc" in body and "task-def" in body

    r2 = client.get("/tasks?state=failed")
    body2 = r2.get_data(as_text=True)
    assert "task-def" in body2
    assert "task-abc" not in body2


def test_task_detail_html(client, db):
    _seed(db)
    r = client.get("/tasks/task-abc")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "task-abc" in body
    assert "completed" in body
    assert "summary" in body  # artifact name
    assert "Q1 sales" in body  # artifact text


def test_task_detail_json(client, db):
    _seed(db)
    r = client.get("/tasks/task-abc?format=json")
    assert r.status_code == 200
    blob = r.get_json()
    assert blob["task_id"] == "task-abc"
    assert any(e["kind"] == "artifact" for e in blob["events"])


def test_task_detail_404_for_unknown(client):
    r = client.get("/tasks/does-not-exist")
    assert r.status_code == 404


def test_task_detail_shows_referenced_task_links(client, db):
    _seed(db)
    r = client.get("/tasks/task-def")
    body = r.get_data(as_text=True)
    assert "task-abc" in body  # referenced
    assert "/tasks/task-abc" in body
