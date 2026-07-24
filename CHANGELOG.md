# Changelog

All notable changes to Skein are documented here. Format roughly follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows semantic versioning once it reaches v1.0.0.

## [Unreleased]

### Added
- `/contexts` and `/contexts/<id>` views — browse A2A `contextId` groups as merged conversations across multiple tasks.
- Free-text search on `/tasks` (matches task id, context id, error fields, and raw payload bodies).
- HTMX auto-refresh on `/tasks` (every 5 s).
- `skein clean --older-than 7d` for retention; supports `--dry-run`.
- `skein/states.py` — single source of truth for A2A task state strings, enforced by `tests/test_states.py` (see Fixed).
- `states.sql_in()` / `failure_states_sql()` for building state `IN (...)` clauses, and `is_failure_state()` / `is_terminal_state()` / `is_valid_state()` / `all_states()` call-time accessors.
- `ParsedMessage.extra` — top-level payload fields outside the six JSON-RPC envelope members are preserved and persisted to the (previously always-`NULL`) `messages.extra_json` column.
- `skein/_version.py` — version sourced from installed package metadata.
- `CHANGELOG.md`.

### Changed
- README rewritten around the specific debugging-moment value prop, with screenshots and an explicit "what Skein isn't" table calling out A2A Inspector, AOP, Agent Gateway, OpenTelemetry+Datadog, OWASP AOS.
- NSIS installer takes `APP_VERSION` via `/D` so the bundle version comes from `pyproject.toml`.
- CI now runs `ruff check` and `mypy` in addition to pytest.

### Fixed
- `skein/states.py` was advertised as the single source of truth but was not one: `validator.py` re-declared all seven states independently, and `('failed','rejected','canceled')` was hardcoded at nine call sites in `failures/detector.py`, `dashboard/routes.py` and `skein_mcp/tools.py`. All now derive from `states.py`, guarded by a test that fails if a state is added and a call site misses it.
- README claimed cascade detection is "deterministic, not heuristic". Only the `referenceTaskIds` signal is deterministic; the same-`contextId` 300-second window is a temporal heuristic. Both are now described accurately, alongside the `via` label that already distinguished them.
- Cascade detection reported a task as affected even when that task had already reached a terminal state *before* the failure it supposedly cascaded from. It is now excluded by an ordering constraint.
- `ParsedTask.state_timestamp` was parsed and unit-tested but never persisted; it is now stored as `state_transitions.at`, preferred over message and capture time.

### Removed
- `parser.py`'s `_TRACEPARENT_RE = None  # populated lazily` — never populated, never read.
- `parser.py`'s `__all_terminal` re-export — dead, `noqa`-silenced, and its back-compat justification was false.
- `detector.py`'s `from ..states import FAILURE_STATES, TERMINAL_STATES  # noqa: F401` — neither name was used anywhere in the file.
- `skein/sdk/a2a_patch.py` — never verified against the real `a2a-sdk` package and not part of the v1 supported integration. Webhook is the supported path; users wanting decorator-based capture should use [AOP](https://github.com/aop-protocol/aop).
- `patch_a2a_sdk` parameter on `skein.sdk.client.install`.

### Tests
- 130/130 passing, 91% coverage (was 71/71 at 71%). Added: `test_retention.py` (4), `test_mcp_protocol.py` (2 — round-trip via real `mcp` library, not just pure tool fns), `test_states.py` (20 — state drift guard), `test_cli.py` (15), `test_jobs.py` (10 — scheduler registration).
- `cli.py` 0% → 99%, `failures/jobs.py` 0% → 100%, `_demo_data.py` 0% → 100%, `states.py` 63% → 100%.

## [0.1.0] — 2026-04-19

Initial public release. Six development phases:

- **Phase 1** — capture spine: `POST /trace/ingest`, SQLite schema, A2A JSON-RPC parser, transactional normalizer with idempotency on `(task_id, payload_hash)`.
- **Phase 2** — Flask + HTMX dashboard with dark-themed timeline view, server-rendered task detail, JSON export.
- **Phase 3** — failure detection: stale-task sweep (APScheduler), cascade detection via `referenceTaskIds` + `contextId`, `/failures` page, `skein serve` and `skein demo` CLI commands.
- **Phase 4** — `skein-mcp` stdio server with 6 tools for Claude Desktop / Claude Code: `get_recent_failures`, `get_task_timeline`, `list_active_agents`, `get_agent_activity`, `query_failure_patterns`, `export_trace`.
- **Phase 5** — packaging: PyInstaller spec, NSIS installer, GitHub Actions CI matrix (Python 3.10/3.11/3.12 × Ubuntu/Windows).
- **Phase 6** — strategic positioning + spec compliance + OTLP trace context capture: passive A2A spec validator, `spec_warnings` table and `/spec-warnings` page, W3C `traceparent` extraction from message and task metadata, `docs/ARCHITECTURE.md`.
