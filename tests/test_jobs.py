"""Tests for the APScheduler wiring in skein/failures/jobs.py.

The stale-task sweeper is a headline feature — the README promises "with
stale-task sweeper running every 60s". sweep_stale_tasks() itself was tested,
but nothing tested that it is ever *scheduled*, so the whole sweeper could
have been silently unwired without a test noticing. These tests cover the
registration, not just the sweep.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from skein.config import Config
from skein.db import open_db
from skein.failures.jobs import _run_sweep, _run_vacuum, start_scheduler
from skein.ingest.normalizer import store
from skein.ingest.parser import parse
from tests.conftest import load_fixture


@pytest.fixture
def cfg(tmp_path):
    return Config(db_path=str(tmp_path / "jobs.db"), default_task_timeout_seconds=42)


@pytest.fixture
def scheduler(cfg):
    """A started scheduler, always shut down again."""
    sched = start_scheduler(cfg)
    try:
        yield sched
    finally:
        sched.shutdown(wait=False)


# ---------- scheduling registration ----------

def test_start_scheduler_starts_running(scheduler):
    assert scheduler.running


def test_start_scheduler_registers_exactly_the_two_expected_jobs(scheduler):
    assert {j.id for j in scheduler.get_jobs()} == {"stale_sweep", "db_vacuum"}


def test_stale_sweep_is_scheduled_every_60_seconds(scheduler, cfg):
    """The headline sweeper must actually be wired to a 60s interval trigger."""
    job = scheduler.get_job("stale_sweep")
    assert job is not None
    assert job.func is _run_sweep
    assert job.trigger.interval == timedelta(seconds=60)
    # ...and handed the config it needs to do the sweep.
    assert job.args == (cfg.db_path, cfg.default_task_timeout_seconds)


def test_stale_sweep_does_not_pile_up_on_slow_runs(scheduler):
    """max_instances/coalesce keep a slow sweep from stacking or backfilling."""
    job = scheduler.get_job("stale_sweep")
    assert job.max_instances == 1
    assert job.coalesce is True


def test_db_vacuum_is_scheduled_daily(scheduler, cfg):
    job = scheduler.get_job("db_vacuum")
    assert job is not None
    assert job.func is _run_vacuum
    assert job.trigger.interval == timedelta(hours=24)
    assert job.args == (cfg.db_path,)
    assert job.max_instances == 1


def test_scheduler_runs_in_utc(scheduler):
    assert str(scheduler.timezone) == "UTC"


# ---------- the scheduled callables actually work against a db path ----------

def test_run_sweep_marks_stale_task_failed_through_a_db_path(cfg):
    """_run_sweep opens its own connection from a path — exercise that seam."""
    conn = open_db(cfg.db_path)
    try:
        store(conn, parse(load_fixture("01_message_send_request.json")), direction="outbound")
        old = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
        conn.execute("UPDATE tasks SET created_at = ?, updated_at = ?", (old, old))
    finally:
        conn.close()

    _run_sweep(cfg.db_path, 300)

    conn = open_db(cfg.db_path)
    try:
        row = conn.execute(
            "SELECT current_state, error_code FROM tasks WHERE id = 'task-abc'"
        ).fetchone()
    finally:
        conn.close()
    assert row["current_state"] == "failed"
    assert row["error_code"] == "skein/timeout"


def test_run_sweep_logs_marked_tasks(cfg, caplog):
    conn = open_db(cfg.db_path)
    try:
        store(conn, parse(load_fixture("01_message_send_request.json")), direction="outbound")
        old = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
        conn.execute("UPDATE tasks SET created_at = ?, updated_at = ?", (old, old))
    finally:
        conn.close()

    with caplog.at_level("INFO", logger="skein.failures.jobs"):
        _run_sweep(cfg.db_path, 300)
    assert "task-abc" in caplog.text


def test_run_sweep_is_quiet_when_nothing_is_stale(cfg, caplog):
    open_db(cfg.db_path).close()
    with caplog.at_level("INFO", logger="skein.failures.jobs"):
        _run_sweep(cfg.db_path, 300)
    assert caplog.text == ""


def test_run_vacuum_leaves_the_db_usable(cfg):
    conn = open_db(cfg.db_path)
    try:
        store(conn, parse(load_fixture("01_message_send_request.json")), direction="outbound")
    finally:
        conn.close()

    _run_vacuum(cfg.db_path)

    conn = open_db(cfg.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"] == 1
    finally:
        conn.close()
