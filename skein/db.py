"""SQLite connection management and schema initialization."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

SCHEMA_VERSION = 2


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


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Add OTLP trace columns to messages and spec_warnings table."""
    for col, decl in (
        ("trace_id", "TEXT"),
        ("span_id", "TEXT"),
        ("traceparent", "TEXT"),
    ):
        if not _column_exists(conn, "messages", col):
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {decl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_trace_id ON messages(trace_id)")
    # spec_warnings table is created by the IF NOT EXISTS block in schema.sql,
    # which executescript() above already ran.


def init_schema(conn: sqlite3.Connection) -> None:
    """Apply schema if not already at SCHEMA_VERSION. Idempotent.

    Migration model: schema.sql is the canonical fresh-install schema. For
    pre-existing DBs we ALTER from version N to version N+1.
    """
    conn.executescript(_load_schema_sql())
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = row["v"] if row and row["v"] is not None else 0
    if current < 2:
        _migrate_v1_to_v2(conn)
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
