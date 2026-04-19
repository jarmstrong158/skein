# Skein

Local-first observability for [A2A](https://github.com/a2aproject/A2A) multi-agent message flows. Captures JSON-RPC payloads exchanged between A2A agents and renders them as human-readable timelines with failure detection.

> **Status:** v0.1 — Phase 1 (capture spine) complete. Dashboard, MCP server, and SDK shipping in subsequent phases.

## What it does

Every serious A2A developer today reconstructs conversation flows from JSON-RPC log dumps by hand. Skein captures those flows once and lets you read them as a timeline, query them via Claude through MCP, and pinpoint failures fast.

Three primary surfaces (when complete):
1. **Live dashboard** — Flask web UI showing active tasks, recent failures, agent activity.
2. **Timeline view** — for any `taskId`, the full ordered conversation between agents with state transitions, errors, and artifacts.
3. **MCP server** — ask Claude "what failed in the last hour" or "show me the conversation for task X."

## Quickstart (Phase 1)

```bash
git clone https://github.com/jarmstrong158/skein
cd skein
python -m venv .venv
.venv\Scripts\activate         # Windows
pip install -e ".[dev]"
cp config.example.json config.json

# Run the server (with stale-task sweeper running every 60s)
skein serve
# -> http://127.0.0.1:5050

# In another terminal, send a synthetic 3-agent A2A workflow
skein demo

# Open http://127.0.0.1:5050 to inspect

# Or ingest your own A2A payload directly:
curl -X POST http://127.0.0.1:5050/trace/ingest \
  -H "Content-Type: application/json" \
  -d '{"payload": {...A2A JSON-RPC...}, "direction": "outbound"}'
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

## Endpoints (Phase 1)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/trace/ingest` | Accept one A2A JSON-RPC payload. Body: `{payload, direction, captured_at?, protocol_version?}` |
| `POST` | `/trace/agent_card` | Upsert an agent card (full agent identity + skills) |
| `GET` | `/trace/health` | Returns `{status, db_size_mb, message_count_24h}` |

## Tests

```bash
pytest -q
```

16 tests covering parser, ingest endpoints, idempotency, reference-task linkage, agent card upsert, and end-to-end flow against fixture payloads.

## Roadmap

- **Phase 1 — Capture spine** ✅ ingest webhook, SQLite schema, parser/normalizer, tests
- **Phase 2 — Timeline + dashboard** ✅ Flask + HTMX dashboard, server-rendered timeline view, dark theme
- **Phase 3 — Failure detection + SDK** ✅ stale-task sweep (APScheduler), cascade detection via `referenceTaskIds`+`contextId`, `/failures` page, Python SDK with optional `a2a-sdk` monkey-patch, `skein demo` toy agent, `skein serve` CLI
- **Phase 4 — MCP server** 6 tools for Claude Desktop / Claude Code
- **Phase 5 — Packaging + release** PyInstaller bundle, NSIS installer, GitHub Actions CI, v1.0

## License

MIT
