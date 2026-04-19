-- Skein schema v1
-- Designed to be Postgres-portable: no SQLite-specific types beyond
-- INTEGER PRIMARY KEY AUTOINCREMENT (trivially swapped for SERIAL/IDENTITY).

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agents (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    endpoint_url    TEXT,
    card_json       TEXT,
    first_seen_at   TIMESTAMP NOT NULL,
    last_seen_at    TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agents_last_seen ON agents(last_seen_at DESC);

CREATE TABLE IF NOT EXISTS tasks (
    id                  TEXT PRIMARY KEY,
    context_id          TEXT,
    initiating_agent_id TEXT REFERENCES agents(id),
    current_state       TEXT NOT NULL,
    created_at          TIMESTAMP NOT NULL,
    updated_at          TIMESTAMP NOT NULL,
    terminal_at         TIMESTAMP,
    timeout_seconds     INTEGER,
    error_code          TEXT,
    error_message       TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_state   ON tasks(current_state);
CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_context ON tasks(context_id);

CREATE TABLE IF NOT EXISTS messages (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id           TEXT NOT NULL REFERENCES tasks(id),
    sequence          INTEGER NOT NULL,
    direction         TEXT NOT NULL,
    method            TEXT NOT NULL,
    from_agent_id     TEXT REFERENCES agents(id),
    to_agent_id       TEXT REFERENCES agents(id),
    payload_json      TEXT NOT NULL,
    payload_hash      TEXT NOT NULL,
    protocol_version  TEXT,
    extra_json        TEXT,
    captured_at       TIMESTAMP NOT NULL,
    occurred_at       TIMESTAMP,
    -- W3C Trace Context / OTLP correlation. Skein extracts these from the
    -- ingest body's optional `traceparent` field (set by SDKs that captured
    -- the HTTP header) AND from a2a Message.metadata / Task.metadata.
    -- Stored verbatim so v1.1 OTLP export can forward them to Datadog/Jaeger.
    trace_id          TEXT,
    span_id           TEXT,
    traceparent       TEXT,
    UNIQUE(task_id, payload_hash)
);
CREATE INDEX IF NOT EXISTS idx_messages_task_seq  ON messages(task_id, sequence);
CREATE INDEX IF NOT EXISTS idx_messages_captured  ON messages(captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_trace_id  ON messages(trace_id);

-- Spec compliance warnings raised at ingest time. Distinct from operational
-- failures (tasks.error_*) — these say "the message itself violated the
-- A2A spec", not "the agent's work failed".
CREATE TABLE IF NOT EXISTS spec_warnings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      TEXT REFERENCES tasks(id),
    message_id   INTEGER REFERENCES messages(id),
    agent_id     TEXT REFERENCES agents(id),
    severity     TEXT NOT NULL,        -- 'warning' | 'error'
    code         TEXT NOT NULL,        -- e.g. 'a2a/missing-required-field'
    description  TEXT NOT NULL,
    field_path   TEXT,                 -- dotted path of the offending field
    raised_at    TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_warnings_task    ON spec_warnings(task_id);
CREATE INDEX IF NOT EXISTS idx_warnings_message ON spec_warnings(message_id);
CREATE INDEX IF NOT EXISTS idx_warnings_raised  ON spec_warnings(raised_at DESC);

CREATE TABLE IF NOT EXISTS message_references (
    message_id          INTEGER NOT NULL REFERENCES messages(id),
    referenced_task_id  TEXT NOT NULL,
    PRIMARY KEY (message_id, referenced_task_id)
);

CREATE TABLE IF NOT EXISTS state_transitions (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id                  TEXT NOT NULL REFERENCES tasks(id),
    from_state               TEXT,
    to_state                 TEXT NOT NULL,
    at                       TIMESTAMP NOT NULL,
    triggered_by_message_id  INTEGER REFERENCES messages(id)
);
CREATE INDEX IF NOT EXISTS idx_transitions_task ON state_transitions(task_id, at);

CREATE TABLE IF NOT EXISTS artifacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id       TEXT NOT NULL REFERENCES tasks(id),
    name          TEXT,
    mime_type     TEXT,
    content_text  TEXT,
    content_path  TEXT,
    bytes         INTEGER,
    produced_at   TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
