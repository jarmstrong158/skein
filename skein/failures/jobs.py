"""APScheduler glue. One scheduler per app, started in create_app.

Jobs:
  * stale_sweep — every 60s, mark tasks past their timeout as failed.
  * db_vacuum  — daily, sqlite VACUUM.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler

from ..db import open_db
from .detector import sweep_stale_tasks

if TYPE_CHECKING:
    from ..config import Config

log = logging.getLogger(__name__)


def _run_sweep(db_path: str, default_timeout_seconds: int) -> None:
    conn = open_db(db_path)
    try:
        result = sweep_stale_tasks(conn, default_timeout_seconds=default_timeout_seconds)
        if result.marked_failed:
            log.info("stale_sweep marked %d tasks failed: %s", len(result.marked_failed), result.marked_failed)
    finally:
        conn.close()


def _run_vacuum(db_path: str) -> None:
    conn = open_db(db_path)
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()


def start_scheduler(config: Config) -> BackgroundScheduler:
    sched = BackgroundScheduler(daemon=True, timezone="UTC")
    sched.add_job(
        _run_sweep,
        trigger="interval",
        seconds=60,
        args=(config.db_path, config.default_task_timeout_seconds),
        id="stale_sweep",
        max_instances=1,
        coalesce=True,
    )
    sched.add_job(
        _run_vacuum,
        trigger="interval",
        hours=24,
        args=(config.db_path,),
        id="db_vacuum",
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    return sched
