# Skein

[![CI](https://github.com/jarmstrong158/skein/actions/workflows/ci.yml/badge.svg)](https://github.com/jarmstrong158/skein/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**When your local multi-agent A2A system breaks, Skein tells you what happened in plain English.** Drop your webhook URL into your agents, run your workflow, and ask Claude what failed. No cloud, no accounts, no setup beyond `pip install`.

## What Skein is

A local-first, zero-config debugger for multi-agent [A2A](https://github.com/a2aproject/A2A) systems with conversational Claude integration. Built for the developer who wants to `pip install` something and immediately see what their agents are saying to each other.

- **Local-first.** SQLite, runs on `localhost`, no auth, no telemetry.
- **Zero-config ingestion.** One webhook endpoint. Point it at your agents, you're done.
- **Conversational debugging.** MCP server lets Claude Desktop or Claude Code answer "what failed in the last hour" against your captured traces.
- **Spec-aware.** Honors A2A `contextId`, `referenceTaskIds`, and OTLP trace propagation. Cascade detection is deterministic, not heuristic.
- **Windows-packaged.** Single-file installer ships Python and Skein together; no toolchain required for end users.

## What Skein is *not*

Skein deliberately does **not** compete with these — use them for what they're good at:

| Tool | Better choice when... |
|---|---|
| [A2A Inspector](https://github.com/a2aproject/a2a-inspector) | You're developing a single A2A agent and want spec-compliance checks + a live chat debug console. |
| [AOP](https://github.com/aop-protocol/aop) | You want decorator-based instrumentation across MCP, LangChain, CrewAI, A2A, AP2 in one SDK. |
| [Agent Gateway](https://agentgateway.dev) | You're running A2A in production and need a routing/security proxy. |
| OpenTelemetry + Datadog/Jaeger/Honeycomb | You're operating at scale and want enterprise observability with retention and alerting. |
| OWASP AOS | You're building a guardian-agent observability layer at the protocol level. |

Skein is smaller, more opinionated, and more narrowly useful than any of these. That's the feature.

## Install

```bash
git clone https://github.com/jarmstrong158/skein
cd skein
python -m venv .venv
.venv\Scripts\activate          # Windows  (use 'source .venv/bin/activate' on Linux/macOS)
pip install -e ".[dev,mcp]"
cp config.example.json config.json
```

A pre-built `Skein-X.Y.Z-Setup.exe` is published with each GitHub release for users who don't want a Python toolchain. See [packaging/windows/README.md](packaging/windows/README.md) for build details.

## Quickstart

```bash
# Run the dashboard + ingest server (with the stale-task sweeper running every 60s)
skein serve
# -> http://127.0.0.1:5050

# In another terminal, send a synthetic 3-agent A2A workflow
skein demo

# Open the dashboard at http://127.0.0.1:5050
```

To capture from your own A2A agents, have each agent POST every JSON-RPC payload it sends or receives to `http://127.0.0.1:5050/trace/ingest`:

```jsonc
// POST /trace/ingest
{
  "payload": { /* the A2A JSON-RPC envelope, verbatim */ },
  "direction": "outbound",                     // or "inbound", relative to the capturing agent
  "captured_at": "2026-04-19T10:00:00Z",       // optional; server stamps if absent
  "protocol_version": "0.3.1",                 // optional; tagged on the message
  "traceparent": "00-...-...-01"               // optional; W3C trace context
}
```

If your A2A library captures the W3C `traceparent` HTTP header, forward it as the optional top-level field — Skein also auto-extracts trace IDs from `Message.metadata` / `Task.metadata` (the A2A extension pattern), so for many setups you don't need to do anything.

A typical integration is a one-line wrapper around your existing HTTP transport that does the POST. If you'd rather use a library that decorates your agent code, **use [AOP](https://github.com/aop-protocol/aop)** — it spans more protocols and has a richer SDK than anything Skein will ship.

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
| `POST` | `/trace/ingest` | Ingest one A2A JSON-RPC payload (see body shape above) |
| `POST` | `/trace/agent_card` | Upsert an agent card (identity + skills) |
| `GET`  | `/trace/health` | `{status, db_size_mb, message_count_24h}` |
| `GET`  | `/` | Dashboard overview |
| `GET`  | `/tasks` | Filterable task list (`?state=`, `?agent=`) |
| `GET`  | `/tasks/<id>` | Task timeline (HTML; add `?format=json` for JSON) |
| `GET`  | `/agents` | Agent list |
| `GET`  | `/failures` | Failures grouped by error code |
| `GET`  | `/spec-warnings` | Passive A2A spec compliance warnings |

## Spec compliance

Skein passively validates every ingested payload against the A2A spec and records any violations as **spec warnings** — distinct from operational failures. A spec warning says "this message itself was malformed"; an operational failure says "the agent's work failed". They're surfaced in their own dashboard page and badged on individual task detail pages.

## Architecture intent

Skein's ingestion layer is architecturally pluggable. v1 ships a single source — the A2A webhook endpoint — but the parser/normalizer split was designed so additional sources (AOP, OWASP AOS, OTLP receiver) can be added without touching the storage or dashboard. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tests

```bash
pytest -q
```

## Roadmap

- **Phase 1 — Capture spine** ✅ ingest webhook, SQLite schema, parser/normalizer
- **Phase 2 — Timeline + dashboard** ✅ Flask + HTMX dashboard, dark-themed timeline view
- **Phase 3 — Failure detection** ✅ stale-task sweep, cascade detection, `/failures` page, `skein demo` + `skein serve` CLI
- **Phase 4 — MCP server** ✅ 6 tools for Claude Desktop / Claude Code
- **Phase 5 — Packaging + release** ✅ PyInstaller spec, NSIS installer, GitHub Actions CI
- **Phase 6 — OTLP-aware ingestion + spec checks** ✅ W3C trace context capture from A2A metadata, passive spec validator with dedicated `/spec-warnings` page
- **v1.1 — OTLP export.** Forward captured traces as OTLP to Datadog / Jaeger / Honeycomb. Skein stays a local capture layer that can feed enterprise tooling when users scale up.
- **v1.2+** Optional Python SDK for decorator-based capture (only if users specifically request it; the recommended path remains the webhook).
- **Later, demand-driven.** Additional ingestion sources (AOP, OWASP AOS) plugged into the existing parser/normalizer split.

## Contributing

Early-stage portfolio project. PRs welcome — particularly for additional A2A payload shapes, OTLP export, and the v1.1 forwarder.

## License

MIT — see [LICENSE](LICENSE).
