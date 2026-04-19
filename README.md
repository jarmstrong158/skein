# Skein

[![CI](https://github.com/jarmstrong158/skein/actions/workflows/ci.yml/badge.svg)](https://github.com/jarmstrong158/skein/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**Local-first observability for [A2A](https://github.com/a2aproject/A2A) multi-agent message flows.** Captures the JSON-RPC traffic between agents and renders it as readable timelines with cascade-aware failure detection — so you stop reconstructing conversations from log dumps by hand.

## Why

Every serious A2A developer today reconstructs conversation flows from JSON-RPC log dumps by hand. Logs look like a dozen people chatting in different Slack channels at once. Skein captures those flows once and lets you read them as a timeline, query them via Claude through MCP, and pinpoint failures fast.

## What's in the box

| | |
|---|---|
| **Live dashboard** | Flask web UI: active tasks, recent failures, agent activity, auto-refreshing overview |
| **Timeline view** | For any `taskId`, the full ordered conversation between agents — messages, state transitions, artifacts, cascade |
| **Failure detection** | Stale-task sweeper, cascade detection via `referenceTaskIds`+`contextId` (deterministic, per A2A spec) |
| **MCP server** | Six tools so Claude can answer "what failed in the last hour", "show me task X", "what's the most common error this week" |
| **Python SDK** | 3-line install; optional monkey-patch of `a2a-sdk` for zero-call-site auto-capture |
| **Demo workflow** | `skein demo` ships a synthetic 3-agent A2A workflow exercising success, failure, and cascade |

## Install

### Pip (recommended)

```bash
git clone https://github.com/jarmstrong158/skein
cd skein
python -m venv .venv
.venv\Scripts\activate          # Windows  (use 'source .venv/bin/activate' on Linux/macOS)
pip install -e ".[dev,mcp]"
cp config.example.json config.json
```

### Windows installer (no Python required)

Pre-built `Skein-X.Y.Z-Setup.exe` is published with each GitHub release. Bundles Python and Skein into a single installer; see [packaging/windows/README.md](packaging/windows/README.md) for build details.

## Quickstart

```bash
# Run the server (with the stale-task sweeper running every 60s)
skein serve
# -> http://127.0.0.1:5050

# In another terminal, send a synthetic 3-agent A2A workflow
skein demo

# Open the dashboard at http://127.0.0.1:5050 to see:
#   - 3 agents registered
#   - 1 successful task with artifact
#   - 1 explicit failure with referenceTaskIds
#   - 1 cascaded failure
#   - 1 stuck task that the stale-sweep marks failed within ~60s
```

### Use the SDK from your own A2A app

```python
import skein
skein.install(endpoint="http://127.0.0.1:5050")

# For each A2A JSON-RPC payload your app sends or receives:
skein.send(payload, direction="outbound")  # or "inbound"

# Once per agent identity:
skein.send_agent_card(your_agent_card)
```

If you use the official `a2a-sdk`, add `patch_a2a_sdk=True` and skip the per-call instrumentation:

```python
skein.install(endpoint="http://127.0.0.1:5050", patch_a2a_sdk=True)
# ...your existing a2a-sdk code captures automatically.
```

## Ask Claude about your traces (MCP)

Add to your Claude Desktop or Claude Code MCP config:

```json
{
  "mcpServers": {
    "skein": {
      "command": "skein-mcp",
      "env": {
        "SKEIN_DB_PATH": "C:\\path\\to\\your\\skein\\data\\skein.db"
      }
    }
  }
}
```

Six tools: `get_recent_failures`, `get_task_timeline`, `list_active_agents`, `get_agent_activity`, `query_failure_patterns`, `export_trace`.

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/trace/ingest` | Ingest one A2A JSON-RPC payload. Body: `{payload, direction, captured_at?, protocol_version?}` |
| `POST` | `/trace/agent_card` | Upsert an agent card (identity + skills) |
| `GET`  | `/trace/health` | `{status, db_size_mb, message_count_24h}` |
| `GET`  | `/` | Dashboard overview |
| `GET`  | `/tasks` | Filterable task list (`?state=`, `?agent=`) |
| `GET`  | `/tasks/<id>` | Task timeline (HTML; add `?format=json` for JSON) |
| `GET`  | `/agents` | Agent list |
| `GET`  | `/failures` | Failures grouped by error code |

## Tests

```bash
pytest -q
```

49 tests across parser, ingest, timeline, dashboard, failures, SDK, and MCP tools.

## Roadmap

- **Phase 1 — Capture spine** ✅ ingest webhook, SQLite schema, parser/normalizer, 16 tests
- **Phase 2 — Timeline + dashboard** ✅ Flask + HTMX dashboard, dark-themed timeline view, +12 tests
- **Phase 3 — Failure detection + SDK** ✅ stale-task sweep (APScheduler), cascade detection, `/failures` page, Python SDK, `skein demo` + `skein serve` CLI, +12 tests
- **Phase 4 — MCP server** ✅ 6 tools, separate `skein_mcp` package, stdio transport, +9 tests
- **Phase 5 — Packaging + release** ✅ PyInstaller spec, NSIS installer, GitHub Actions CI

## Contributing

This is an early portfolio project. PRs welcome — particularly for JS/TS/Go SDK wrappers, additional A2A payload shapes, and OpenTelemetry export (planned for v2).

## License

MIT — see [LICENSE](LICENSE).
