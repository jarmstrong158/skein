"""Tests for the `skein` CLI.

`serve`, `demo` and `clean` are the three commands the README leads with and
the only interface most users touch, but cli.py had no test coverage at all.
Nothing here binds a port or spawns a real server: create_app / app.run and
the demo's HTTP client are faked at their seams, so what is under test is the
CLI's own wiring — argument parsing, config loading, exit codes, and whether
`serve` actually starts the scheduler.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from skein import app as app_module
from skein.cli import main
from skein.db import open_db
from skein.failures import jobs as jobs_module
from skein.ingest.normalizer import store
from skein.ingest.parser import parse
from skein.sdk import client as sdk_client
from tests.conftest import load_fixture


@pytest.fixture
def config_file(tmp_path):
    """A real config.json pointing at a throwaway db."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"db_path": str(tmp_path / "cli.db"), "port": 5099}))
    return path


class FakeApp:
    """Stands in for the Flask app so `serve` never binds a port."""

    def __init__(self):
        self.run_calls: list[dict] = []

    def run(self, **kwargs):
        self.run_calls.append(kwargs)


@pytest.fixture
def fake_serve(monkeypatch):
    """Fake create_app + record whether the scheduler was started."""
    fake_app = FakeApp()
    started: list = []
    monkeypatch.setattr(app_module, "create_app", lambda cfg: fake_app)
    monkeypatch.setattr(jobs_module, "start_scheduler", lambda cfg: started.append(cfg))
    return fake_app, started


# ---------- argument parsing ----------

def test_main_requires_a_subcommand():
    with pytest.raises(SystemExit):
        main([])


def test_main_rejects_unknown_subcommand():
    with pytest.raises(SystemExit):
        main(["nonsense"])


# ---------- serve ----------

def test_serve_starts_the_scheduler_by_default(config_file, fake_serve):
    fake_app, started = fake_serve
    assert main(["serve", "--config", str(config_file)]) == 0
    assert len(started) == 1, "serve must start the stale-sweep scheduler"
    assert fake_app.run_calls, "serve must actually run the app"


def test_serve_honors_no_scheduler_flag(config_file, fake_serve):
    fake_app, started = fake_serve
    assert main(["serve", "--config", str(config_file), "--no-scheduler"]) == 0
    assert started == []
    assert fake_app.run_calls


def test_serve_binds_host_and_port_from_config(config_file, fake_serve):
    fake_app, _ = fake_serve
    main(["serve", "--config", str(config_file), "--no-scheduler"])
    kwargs = fake_app.run_calls[0]
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 5099
    # A reloader would fork and double-run the scheduler.
    assert kwargs["use_reloader"] is False
    assert kwargs["debug"] is False


def test_serve_passes_config_through_to_the_scheduler(config_file, fake_serve):
    _, started = fake_serve
    main(["serve", "--config", str(config_file)])
    assert started[0].db_path.endswith("cli.db")


# ---------- demo ----------

class RecordingClient:
    def __init__(self):
        self.cards: list[dict] = []
        self.sends: list[tuple[dict, str]] = []

    def send_agent_card(self, card):
        self.cards.append(card)

    def send(self, payload, direction="outbound"):
        self.sends.append((payload, direction))


@pytest.fixture
def recording_client(monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(sdk_client, "install", lambda **kwargs: client)
    return client


def test_demo_registers_agents_and_sends_the_workflow(recording_client):
    assert main(["demo", "--endpoint", "http://127.0.0.1:5099"]) == 0
    assert len(recording_client.cards) == 8, "demo advertises an 8-agent workflow"
    assert recording_client.sends, "demo must send trace payloads"


def test_demo_sends_only_valid_directions(recording_client):
    main(["demo"])
    assert {d for _, d in recording_client.sends} <= {"inbound", "outbound"}


def test_demo_payloads_are_ingestable(recording_client, db):
    """Every demo payload must survive the real parser + normalizer.

    Guards the demo against drifting away from what ingest accepts — a broken
    `skein demo` is the first thing a new user would hit.
    """
    main(["demo"])
    for payload, direction in recording_client.sends:
        store(db, parse(payload), direction=direction)
    states = {
        r["current_state"]
        for r in db.execute("SELECT DISTINCT current_state FROM tasks").fetchall()
    }
    assert {"completed", "failed"} <= states
    # The deliberately malformed payload must have raised spec warnings.
    assert db.execute("SELECT COUNT(*) AS c FROM spec_warnings").fetchone()["c"] > 0


def test_demo_covers_three_contexts(recording_client, db):
    main(["demo"])
    for payload, direction in recording_client.sends:
        store(db, parse(payload), direction=direction)
    contexts = db.execute(
        "SELECT COUNT(DISTINCT context_id) AS c FROM tasks WHERE context_id IS NOT NULL"
    ).fetchone()["c"]
    assert contexts == 3


# ---------- clean ----------

def _seed_old_terminal_task(db_path, *, age_days: int = 30) -> None:
    conn = open_db(db_path)
    try:
        store(conn, parse(load_fixture("01_message_send_request.json")), direction="outbound")
        store(conn, parse(load_fixture("03_task_completed.json")), direction="inbound")
        old = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
        conn.execute("UPDATE tasks SET updated_at = ?, terminal_at = ?", (old, old))
    finally:
        conn.close()


def test_clean_rejects_a_bad_duration(config_file, capsys):
    assert main(["clean", "--older-than", "banana", "--config", str(config_file)]) == 2
    assert "error" in capsys.readouterr().out.lower()


def test_clean_dry_run_reports_without_deleting(config_file, tmp_path, capsys):
    db_path = tmp_path / "cli.db"
    _seed_old_terminal_task(db_path)

    assert main(["clean", "--older-than", "7d", "--config", str(config_file), "--dry-run"]) == 0
    assert "dry-run" in capsys.readouterr().out

    conn = open_db(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"] == 1
    finally:
        conn.close()


def test_clean_deletes_old_terminal_tasks(config_file, tmp_path, capsys):
    db_path = tmp_path / "cli.db"
    _seed_old_terminal_task(db_path)

    assert main(["clean", "--older-than", "7d", "--config", str(config_file)]) == 0
    assert "Cleaned" in capsys.readouterr().out

    conn = open_db(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"] == 0
        assert conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"] == 0
    finally:
        conn.close()


def test_clean_spares_tasks_newer_than_the_cutoff(config_file, tmp_path):
    db_path = tmp_path / "cli.db"
    _seed_old_terminal_task(db_path, age_days=1)

    assert main(["clean", "--older-than", "7d", "--config", str(config_file)]) == 0

    conn = open_db(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"] == 1
    finally:
        conn.close()


def test_clean_defaults_to_seven_days(config_file, tmp_path, capsys):
    db_path = tmp_path / "cli.db"
    _seed_old_terminal_task(db_path)

    assert main(["clean", "--config", str(config_file)]) == 0
    assert "7d" in capsys.readouterr().out
