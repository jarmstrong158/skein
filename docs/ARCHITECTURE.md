# Skein Architecture

Skein has four layers, deliberately decoupled so additional ingestion sources can be added in later versions without touching the storage, dashboard, or MCP server.

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  A2A webhook     │  │  AOP source*     │  │  OTLP receiver*  │   *future, v2+
│  (v1, shipped)   │  │                  │  │                  │
└────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
         │                     │                     │
         └───────────┬─────────┴─────────┬───────────┘
                     ▼                   ▼
         ┌────────────────────────────────────────┐
         │       Parser → ParsedEvent             │   skein/ingest/parser.py
         │  (protocol-agnostic intermediate form) │
         └─────────────────┬──────────────────────┘
                           ▼
         ┌────────────────────────────────────────┐
         │  Validator → SpecWarning[]             │   skein/validator.py
         │  Normalizer → SQLite                   │   skein/ingest/normalizer.py
         └─────────────────┬──────────────────────┘
                           ▼
         ┌────────────────────────────────────────┐
         │  Storage layer (SQLite)                │   skein/db.py + schema.sql
         │  agents, tasks, messages,              │
         │  state_transitions, artifacts,         │
         │  message_references, spec_warnings,    │
         │  schema_version                        │
         └─────────────────┬──────────────────────┘
                           ▼
         ┌────────────────┴───────────────────────┐
         ▼                                        ▼
┌────────────────────┐                ┌──────────────────────┐
│  Dashboard         │                │  MCP server          │
│  Flask + HTMX +    │                │  FastMCP / stdio     │
│  Jinja templates   │                │  (separate process)  │
└────────────────────┘                └──────────────────────┘
```

## Pluggable ingestion (design intent)

The current ingestion source is the A2A webhook (`POST /trace/ingest`). The parser and normalizer were built so **additional sources can be added without changes to storage, dashboard, or MCP**:

- A new source produces a `ParsedEvent` (defined in `skein/ingest/parser.py`).
- The normalizer (`skein/ingest/normalizer.py`) takes `ParsedEvent` + a direction and writes rows. It does not know which protocol the event came from.
- Spec validation hooks into the normalizer just before message insert; per-protocol validators can be registered the same way.

Concretely, this means future sources like AOP (decorator-based) or OWASP AOS (guardian-agent), or an OTLP receiver translating OTel spans into A2A-shaped events, can be implemented as new ingest packages that emit `ParsedEvent`. We're not pre-building those — but we are keeping the seam clean.

## Why SQLite (and how Postgres-portable the schema is)

Single-user local tooling. Zero-config. Zero-dependency. The schema avoids SQLite-isms beyond `INTEGER PRIMARY KEY AUTOINCREMENT` (trivially `SERIAL`/`IDENTITY` in Postgres). All timestamps are stored as ISO 8601 strings to avoid Python 3.12's deprecated TIMESTAMP converter and to remain portable.

## Trace correlation

A2A propagates W3C Trace Context per the OpenTelemetry standard. Three places trace IDs can appear in an A2A message; Skein looks in all of them, in this order:

1. The ingest body's optional top-level `traceparent` field (set by SDKs that captured the HTTP header before the JSON-RPC body was reconstructed; see [kagent#1295](https://github.com/kagent-dev/kagent/issues/1295) for why this is necessary).
2. `payload.params.message.metadata.traceparent` or `metadata.trace_id`.
3. `payload.result.metadata.traceparent` or `metadata.trace_id`.

The first match wins. Stored in `messages.trace_id` / `messages.span_id` / `messages.traceparent` for v1.1 OTLP export to forward verbatim.

## Schema migrations

`skein/db.py` tracks `SCHEMA_VERSION` against the `schema_version` table and applies forward migrations (e.g. `_migrate_v1_to_v2`) for pre-existing databases. Fresh installs apply `schema.sql` directly. Each migration must be idempotent (`ALTER TABLE … IF NOT EXISTS`-equivalent guards via a `_column_exists` helper).

## What lives where

| Concern | Module |
|---|---|
| HTTP ingest endpoints | `skein/ingest/routes.py` |
| Payload → intermediate form | `skein/ingest/parser.py` |
| Intermediate → SQLite + warnings | `skein/ingest/normalizer.py` |
| Spec compliance checks | `skein/validator.py` |
| DB connection + migrations | `skein/db.py` |
| Failure/cascade detection + APScheduler | `skein/failures/` |
| Timeline assembly | `skein/timeline/builder.py` |
| Dashboard routes + templates | `skein/dashboard/` |
| CLI (`serve`, `demo`) | `skein/cli.py` |
| Internal client helper (used by `skein demo`) | `skein/sdk/` *(not public API in v1)* |
| MCP stdio server | `skein_mcp/` *(separate package)* |

## Non-goals

- Multi-tenant / multi-user — local single-user tool by design.
- Authn/authz on the dashboard — localhost only.
- Cloud deployment — local-first; if you need cloud, forward to OpenTelemetry.
- Decorator-based agent instrumentation — use [AOP](https://github.com/aop-protocol/aop).
- Production observability — use OpenTelemetry + Datadog/Jaeger/Honeycomb. Skein is a debugger, not a monitoring system.
