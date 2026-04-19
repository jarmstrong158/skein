"""Synthetic A2A workflow used by `skein demo`.

Three contexts, eight agents, mix of completed/failed/cascading/stuck
tasks plus deliberate spec violations, so the dashboard has rich
realistic-looking data after one run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class Scenarios:
    agent_cards: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)  # {payload, direction}
    summary_lines: list[str] = field(default_factory=list)


# Stable trace IDs used across the scenarios so dashboards show real OTLP
# correlation; format is W3C `00-<32 hex>-<16 hex>-01`.
TP_RESEARCH = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
TP_OPS      = "00-a3ce929d0e0e47364bf92f3577b34da6-b7f067aa0ba902af-01"
TP_INDEX    = "00-1212121212121212121212121212dada-cafebabec0ffee01-01"


AGENTS: dict[str, dict[str, Any]] = {
    "orchestrator": {
        "name": "Orchestrator",
        "url": "https://orchestrator.demo/agent",
        "version": "1.0.0",
        "description": "Routes user requests to specialist agents.",
        "skills": [{"id": "route", "name": "Route requests"}],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
    },
    "researcher": {
        "name": "Researcher",
        "url": "https://researcher.demo/agent",
        "version": "1.0.0",
        "description": "Gathers facts from the web and internal sources.",
        "skills": [{"id": "web_search", "name": "Search the public web"},
                   {"id": "doc_search", "name": "Search internal docs"}],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
    },
    "writer": {
        "name": "Writer",
        "url": "https://writer.demo/agent",
        "version": "1.0.0",
        "description": "Produces drafts from collected research.",
        "skills": [{"id": "draft", "name": "Draft prose"}],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
    },
    "reviewer": {
        "name": "Reviewer",
        "url": "https://reviewer.demo/agent",
        "version": "1.0.0",
        "description": "Critiques drafts for tone and accuracy.",
        "skills": [{"id": "critique", "name": "Critique draft"}],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
    },
    "translator": {
        "name": "Translator",
        "url": "https://translator.demo/agent",
        "version": "1.0.0",
        "description": "Translates approved drafts.",
        "skills": [{"id": "translate", "name": "Translate text"}],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
    },
    "ops": {
        "name": "Ops Agent",
        "url": "https://ops.demo/agent",
        "version": "0.9.0",
        "description": "Runs operational scripts and checks.",
        "skills": [{"id": "deploy_check", "name": "Pre-deploy validation"},
                   {"id": "metrics_pull", "name": "Pull production metrics"}],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
    },
    "indexer": {
        "name": "Indexer",
        "url": "https://indexer.demo/agent",
        "version": "1.2.0",
        "description": "Indexes long-running document corpora.",
        "skills": [{"id": "scrape_index", "name": "Scrape and index sites"}],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
    },
    "alerts": {
        "name": "Alerts",
        "url": "https://alerts.demo/agent",
        "version": "1.0.0",
        "description": "Notifies humans when workflows complete or fail.",
        "skills": [{"id": "page", "name": "Send a page"}],
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
    },
}


def _iso(offset_seconds: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


def _send(s: Scenarios, payload: dict[str, Any], direction: str) -> None:
    s.events.append({"payload": payload, "direction": direction})


def _msg_send(
    *, msg_id: str, task_id: str, ctx: str, from_url: str, to_url: str | None,
    text: str, refs: list[str] | None = None, traceparent: str | None = None,
    rpc_id: str = "1",
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "messageId": msg_id, "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "taskId": task_id, "contextId": ctx,
        "agentId": from_url, "timestamp": _iso(),
    }
    if refs:
        msg["referenceTaskIds"] = refs
    if traceparent:
        msg["metadata"] = {"traceparent": traceparent}
    params: dict[str, Any] = {"message": msg}
    if to_url:
        params["toAgentId"] = to_url
    return {"jsonrpc": "2.0", "id": rpc_id, "method": "message/send", "params": params}


def _status(task_id: str, ctx: str, state: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": "evt", "result": {
        "kind": "status-update", "taskId": task_id, "contextId": ctx,
        "status": {"state": state, "timestamp": _iso()},
    }}


def _terminal(task_id: str, ctx: str, state: str, *,
              artifacts: list[dict[str, Any]] | None = None,
              error: tuple[int, str] | None = None,
              rpc_id: str = "1") -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": task_id, "contextId": ctx,
        "status": {"state": state, "timestamp": _iso()},
    }
    if artifacts:
        body["artifacts"] = artifacts
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": rpc_id, "result": body}
    if error:
        payload["error"] = {"code": error[0], "message": error[1]}
    return payload


def _build_research_context(s: Scenarios) -> None:
    """ctx-research: Multi-step research workflow with one cascading failure."""
    ctx = "ctx-research-2026-04-19"
    A = AGENTS

    # Task 1: orchestrator -> researcher (success)
    t1 = "task-research-fetch"
    _send(s, _msg_send(
        msg_id="m-r1", task_id=t1, ctx=ctx, rpc_id="1",
        from_url=A["orchestrator"]["url"], to_url=A["researcher"]["url"],
        text="Pull the last 90 days of A2A protocol release notes.",
        traceparent=TP_RESEARCH,
    ), "outbound")
    _send(s, _status(t1, ctx, "working"), "inbound")
    _send(s, _terminal(t1, ctx, "completed", rpc_id="1", artifacts=[{
        "name": "release_notes_summary", "mimeType": "text/markdown",
        "parts": [{"kind": "text", "text":
            "# A2A release notes (last 90 days)\n\n"
            "- 0.3.1 — clarifies referenceTaskIds semantics\n"
            "- 0.3.0 — promotes contextId to required for streaming\n"
            "- 0.2.9 — adds metadata.traceparent extension\n"
        }],
    }]), "inbound")
    s.summary_lines.append(f"[green]OK[/green] {t1}: orchestrator -> researcher -> completed")

    # Task 2: orchestrator -> writer (success, refs t1)
    t2 = "task-research-draft"
    _send(s, _msg_send(
        msg_id="m-r2", task_id=t2, ctx=ctx, rpc_id="2",
        from_url=A["orchestrator"]["url"], to_url=A["writer"]["url"],
        text="Draft a 2-paragraph summary using the release notes.",
        refs=[t1], traceparent=TP_RESEARCH,
    ), "outbound")
    _send(s, _status(t2, ctx, "working"), "inbound")
    _send(s, _terminal(t2, ctx, "completed", rpc_id="2", artifacts=[{
        "name": "summary_v1", "mimeType": "text/plain",
        "parts": [{"kind": "text", "text":
            "Over the last quarter, A2A has tightened its core "
            "primitives: contextId is now required for streaming "
            "interactions, referenceTaskIds gained explicit lineage "
            "semantics, and the metadata.traceparent extension lets "
            "agents propagate W3C trace context end-to-end."
        }],
    }]), "inbound")
    s.summary_lines.append(f"[green]OK[/green] {t2}: writer -> completed")

    # Task 3: orchestrator -> reviewer (fails — auth expired)
    t3 = "task-research-review"
    _send(s, _msg_send(
        msg_id="m-r3", task_id=t3, ctx=ctx, rpc_id="3",
        from_url=A["orchestrator"]["url"], to_url=A["reviewer"]["url"],
        text="Critique the draft for tone and factual accuracy.",
        refs=[t2], traceparent=TP_RESEARCH,
    ), "outbound")
    _send(s, _status(t3, ctx, "working"), "inbound")
    _send(s, _terminal(t3, ctx, "failed", rpc_id="3",
                       error=(-32011, "Reviewer auth token expired (401 Unauthorized)")), "inbound")
    s.summary_lines.append(f"[red]X[/red] {t3}: reviewer auth expired")

    # Task 4: orchestrator -> alerts (cascades — review failed)
    t4 = "task-research-notify"
    _send(s, _msg_send(
        msg_id="m-r4", task_id=t4, ctx=ctx, rpc_id="4",
        from_url=A["orchestrator"]["url"], to_url=A["alerts"]["url"],
        text="Page the on-call about the failed review.",
        refs=[t3], traceparent=TP_RESEARCH,
    ), "outbound")
    _send(s, _terminal(t4, ctx, "completed", rpc_id="4", artifacts=[{
        "name": "page_receipt", "mimeType": "application/json",
        "parts": [{"kind": "text", "text":
            '{"channel":"#oncall-research","status":"delivered"}'}],
    }]), "inbound")
    s.summary_lines.append(f"[green]OK[/green] {t4}: alerts notified on-call about cascade")


def _build_ops_context(s: Scenarios) -> None:
    """ctx-ops: Pre-deploy checks. One success + one stuck task."""
    ctx = "ctx-ops-pre-deploy-1147"
    A = AGENTS

    t1 = "task-ops-validate"
    _send(s, _msg_send(
        msg_id="m-o1", task_id=t1, ctx=ctx, rpc_id="1",
        from_url=A["orchestrator"]["url"], to_url=A["ops"]["url"],
        text="Run pre-deploy validation suite for service `payments-api`.",
        traceparent=TP_OPS,
    ), "outbound")
    _send(s, _status(t1, ctx, "working"), "inbound")
    _send(s, _terminal(t1, ctx, "completed", rpc_id="1", artifacts=[{
        "name": "validation_report", "mimeType": "text/plain",
        "parts": [{"kind": "text", "text":
            "PASS: schema migrations\n"
            "PASS: feature flags coherent\n"
            "PASS: dependency lockfiles clean\n"
            "PASS: integration tests on canary"}],
    }]), "inbound")
    s.summary_lines.append(f"[green]OK[/green] {t1}: pre-deploy checks passed")

    # Stuck: long-running metrics pull, never resolves -> stale-sweep marks failed in ~60s
    t2 = "task-ops-metrics-pull"
    _send(s, _msg_send(
        msg_id="m-o2", task_id=t2, ctx=ctx, rpc_id="2",
        from_url=A["orchestrator"]["url"], to_url=A["ops"]["url"],
        text="Pull 7-day production latency histogram for payments-api.",
        traceparent=TP_OPS,
    ), "outbound")
    s.summary_lines.append(f"[yellow]...[/yellow] {t2}: left submitted; stale-sweep will fail it in ~60s")


def _build_indexing_context(s: Scenarios) -> None:
    """ctx-indexing: A long-running indexer + a deliberately spec-malformed payload."""
    ctx = "ctx-indexer-corpus-22"
    A = AGENTS

    # Long-running indexer with input-required interrupt
    t1 = "task-indexer-corpus"
    _send(s, _msg_send(
        msg_id="m-i1", task_id=t1, ctx=ctx, rpc_id="1",
        from_url=A["orchestrator"]["url"], to_url=A["indexer"]["url"],
        text="Index https://docs.example.org/* (full crawl).",
        traceparent=TP_INDEX,
    ), "outbound")
    _send(s, _status(t1, ctx, "working"), "inbound")
    _send(s, _status(t1, ctx, "input-required"), "inbound")
    _send(s, _msg_send(
        msg_id="m-i2", task_id=t1, ctx=ctx, rpc_id="2",
        from_url=A["orchestrator"]["url"], to_url=A["indexer"]["url"],
        text="Yes, include the /api subpath.",
        traceparent=TP_INDEX,
    ), "outbound")
    _send(s, _status(t1, ctx, "working"), "inbound")
    _send(s, _terminal(t1, ctx, "completed", rpc_id="3", artifacts=[{
        "name": "index_stats", "mimeType": "application/json",
        "parts": [{"kind": "text", "text":
            '{"pages":2148,"tokens":4720333,"duration_seconds":94}'}],
    }]), "inbound")
    s.summary_lines.append(f"[green]OK[/green] {t1}: indexer completed after input-required")

    # Deliberately malformed payload to trigger spec_warnings
    t2 = "task-indexer-bad-shape"
    bad_payload = {
        # jsonrpc 1.0 (wrong version), missing messageId/role/parts
        "jsonrpc": "1.0", "id": "x", "method": "message/send",
        "params": {"message": {
            "taskId": t2, "contextId": ctx,
            "metadata": {"traceparent": TP_INDEX},
        }},
    }
    _send(s, bad_payload, "outbound")
    s.summary_lines.append(f"[yellow]![/yellow] {t2}: deliberate spec violations to populate /spec-warnings")


def build_scenarios() -> Scenarios:
    s = Scenarios(agent_cards=list(AGENTS.values()))
    _build_research_context(s)
    # Tiny pause so timestamps in different contexts visibly differ.
    time.sleep(0.05)
    _build_ops_context(s)
    time.sleep(0.05)
    _build_indexing_context(s)
    return s
