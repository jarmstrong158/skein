# Changelog

All notable changes to Skein are documented here. Format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows semantic versioning once it reaches v1.0.0.

## [Unreleased]

### Added
- `/contexts` and `/contexts/<id>` views — browse A2A `contextId` groups as merged conversations across multiple tasks.
- Free-text search on `/tasks` (matches task id, context id, error fields, and raw payload bodies).
- HTMX auto-refresh on `/tasks` (every 5 s).
- `skein clean --older-than 7d` for retention; supports `--dry-run`.
- `skein/states.py` — single source of truth for A2A task state strings.
- `skein/_version.py` — version sourced from installed package metadata.
- `CHANGELOG.md`.

### Changed
- README rewritten around the specific debugging-moment value prop, with screenshots and an explicit "what Skein isn't" table calling out A2A Inspector, AOP, Agent Gateway, OpenTelemetry+Datadog, OWASP AOS.
- NSIS installer takes `APP_VERSION` via `/D` so the bundle version comes from `pyproject.toml`.
- CI now runs `ruff check` and `mypy` in addition to pytest.

### Removed
- `skein/sdk/a2a_patch.py` — never verified against the real `a2a-sdk` package and not part of the v1 supported integration. Webhook is the supported path; users wanting decorator-based capture should use [AOP](https://github.com/aop-protocol/aop).
- `patch_a2a_sdk` parameter on `skein.sdk.client.install`.

### Tests
- 71/71 passing. Added: `test_retention.py` (4), `test_mcp_protocol.py` (2 — round-trip via real `mcp` library, not just pure tool fns).

## [0.1.0] — 2026-04-19

Initial public release. Six development phases:

- **Phase 1** — capture spine: `POST /trace/ingest`, SQLite schema, A2A JSON-RPC parser, transactional normalizer with idempotency on `(task_id, payload_hash)`.
- **Phase 2** — Flask + HTMX dashboard with dark-themed timeline view, server-rendered task detail, JSON export.
- **Phase 3** — failure detection: stale-task sweep (APScheduler), cascade detection via `referenceTaskIds` + `contextId`, `/failures` page, `skein serve` and `skein demo` CLI commands.
- **Phase 4** — `skein-mcp` stdio server with 6 tools for Claude Desktop / Claude Code: `get_recent_failures`, `get_task_timeline`, `list_active_agents`, `get_agent_activity`, `query_failure_patterns`, `export_trace`.
- **Phase 5** — packaging: PyInstaller spec, NSIS installer, GitHub Actions CI matrix (Python 3.10/3.11/3.12 × Ubuntu/Windows).
- **Phase 6** — strategic positioning + spec compliance + OTLP trace context capture: passive A2A spec validator, `spec_warnings` table and `/spec-warnings` page, W3C `traceparent` extraction from message and task metadata, `docs/ARCHITECTURE.md`.
