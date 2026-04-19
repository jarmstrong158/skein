"""SQLite connection management and schema initialization."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 1


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection with sane defaults: row factory, FK enforcement, WAL."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _load_schema_sql() -> str:
    return resources.files("skein").joinpath("schema.sql").read_text()


def init_schema(conn: sqlite3.Connection) -> None:
    """Apply schema if not already at SCHEMA_VERSION. Idempotent."""
    conn.executescript(_load_schema_sql())
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = row["v"] if row and row["v"] is not None else 0
    if current < SCHEMA_VERSION:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Connect and ensure schema is applied."""
    conn = connect(db_path)
    init_schema(conn)
    return conn


def get_db():
    """Per-request connection helper for Flask routes.

    Returns the shared connection if app.config['SKEIN_SHARED_DB'] is set
    (used by tests); otherwise opens a fresh per-request connection cached
    on flask.g.
    """
    from flask import current_app, g
    shared = current_app.config.get("SKEIN_SHARED_DB")
    if shared is not None:
        return shared
    if "db" not in g:
        g.db = open_db(current_app.config["SKEIN_CONFIG"].db_path)
    return g.db
