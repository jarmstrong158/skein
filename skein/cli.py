"""Command-line interface for Skein."""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone

from rich.console import Console

console = Console()


def _cmd_serve(args: argparse.Namespace) -> int:
    from .app import create_app
    from .config import Config
    from .failures.jobs import start_scheduler

    cfg = Config.load(args.config)
    app = create_app(cfg)
    if not args.no_scheduler:
        start_scheduler(cfg)
        console.print(f"[dim]scheduler started (stale_sweep every 60s)[/dim]")
    console.print(f"[bold green]Skein[/bold green] serving at [bold]http://{cfg.host}:{cfg.port}[/bold]")
    app.run(host=cfg.host, port=cfg.port, debug=False, use_reloader=False)
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    """Run a self-contained 3-agent A2A toy workflow against a Skein endpoint.

    No real agents, no a2a-sdk needed — just synthetic JSON-RPC payloads that
    exercise every part of the Skein store: success path, failed path, cascade.
    """
    from .sdk import client as sdk_client  # internal helper, not public API

    client = sdk_client.install(endpoint=args.endpoint, raise_on_error=False)
    console.print(f"[bold]Skein demo[/bold] -> {args.endpoint}")

    agents = {
        "orchestrator": {
            "name": "Orchestrator",
            "url": "https://orchestrator.demo/agent",
            "version": "1.0.0",
            "skills": [{"id": "route", "name": "Route requests"}],
        },
        "researcher": {
            "name": "Researcher",
            "url": "https://researcher.demo/agent",
            "version": "1.0.0",
            "skills": [{"id": "search", "name": "Search the web"}],
        },
        "writer": {
            "name": "Writer",
            "url": "https://writer.demo/agent",
            "version": "1.0.0",
            "skills": [{"id": "draft", "name": "Draft a summary"}],
        },
    }
    for card in agents.values():
        client.send_agent_card(card)
    console.print(f"  registered [cyan]{len(agents)}[/cyan] agents")

    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    ctx = "ctx-demo-001"

    # ---- Successful task: orchestrator -> researcher ------------------------
    task_a = "task-research-001"
    client.send(
        {
            "jsonrpc": "2.0", "id": "1", "method": "message/send",
            "params": {
                "message": {
                    "messageId": "m1", "role": "user",
                    "parts": [{"kind": "text", "text": "What's the latest on A2A protocol?"}],
                    "taskId": task_a, "contextId": ctx,
                    "agentId": agents["orchestrator"]["url"],
                    "timestamp": now(),
                },
                "toAgentId": agents["researcher"]["url"],
            },
        },
        direction="outbound",
    )
    client.send(
        {"jsonrpc": "2.0", "id": "1", "result": {
            "kind": "status-update", "taskId": task_a, "contextId": ctx,
            "status": {"state": "working", "timestamp": now()},
        }},
        direction="inbound",
    )
    time.sleep(0.2)
    client.send(
        {"jsonrpc": "2.0", "id": "1", "result": {
            "id": task_a, "contextId": ctx,
            "status": {"state": "completed", "timestamp": now()},
            "artifacts": [{
                "name": "research_notes", "mimeType": "text/plain",
                "parts": [{"kind": "text", "text": "A2A is now Linux Foundation-governed (Apr 2025)."}],
            }],
        }},
        direction="inbound",
    )
    console.print(f"  [green]OK[/green] {task_a}: orchestrator -> researcher -> completed")

    # ---- Failing task: orchestrator -> writer (depends on task_a) -----------
    task_b = "task-draft-001"
    client.send(
        {
            "jsonrpc": "2.0", "id": "2", "method": "message/send",
            "params": {
                "message": {
                    "messageId": "m2", "role": "user",
                    "parts": [{"kind": "text", "text": "Draft a summary using the research."}],
                    "taskId": task_b, "contextId": ctx,
                    "referenceTaskIds": [task_a],
                    "agentId": agents["orchestrator"]["url"],
                    "timestamp": now(),
                },
                "toAgentId": agents["writer"]["url"],
            },
        },
        direction="outbound",
    )
    client.send(
        {"jsonrpc": "2.0", "id": "2",
         "result": {
             "id": task_b, "contextId": ctx,
             "status": {"state": "failed", "timestamp": now()},
         },
         "error": {"code": -32002, "message": "Writer agent unreachable (502 Bad Gateway)"},
        },
        direction="inbound",
    )
    console.print(f"  [red]X[/red] {task_b}: writer unreachable (refs {task_a})")

    # ---- Cascade: orchestrator's own follow-up task fails because writer's did
    task_c = "task-followup-001"
    client.send(
        {
            "jsonrpc": "2.0", "id": "3", "method": "message/send",
            "params": {
                "message": {
                    "messageId": "m3", "role": "user",
                    "parts": [{"kind": "text", "text": "Notify on completion."}],
                    "taskId": task_c, "contextId": ctx,
                    "referenceTaskIds": [task_b],
                    "agentId": agents["orchestrator"]["url"],
                    "timestamp": now(),
                },
            },
        },
        direction="outbound",
    )
    client.send(
        {"jsonrpc": "2.0", "id": "3",
         "result": {
             "id": task_c, "contextId": ctx,
             "status": {"state": "failed", "timestamp": now()},
         },
         "error": {"code": -32099, "message": "Upstream task failed"},
        },
        direction="inbound",
    )
    console.print(f"  [red]X[/red] {task_c}: cascaded failure from {task_b}")

    # ---- Stale task (will be marked failed by stale_sweep within ~60s) -----
    task_d = "task-stuck-001"
    client.send(
        {
            "jsonrpc": "2.0", "id": "4", "method": "message/send",
            "params": {
                "message": {
                    "messageId": "m4", "role": "user",
                    "parts": [{"kind": "text", "text": "Long-running scrape."}],
                    "taskId": task_d, "contextId": "ctx-demo-002",
                    "agentId": agents["orchestrator"]["url"],
                    "timestamp": now(),
                },
            },
        },
        direction="outbound",
    )
    console.print(f"  [yellow]...[/yellow] {task_d}: left in 'submitted' state to demo stale-sweep")

    console.print(
        f"\n[bold]Open[/bold] [cyan]{args.endpoint}[/cyan] to inspect.\n"
        f"  * Overview / Tasks / Failures show all the above\n"
        f"  * Task detail for {task_b} shows cascade to {task_c}\n"
        f"  * {task_d} will appear under Failures within ~60s if scheduler is running"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="skein", description="Skein — A2A trace observability")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="Run the Skein dashboard + ingest server")
    p_serve.add_argument("--config", default="./config.json")
    p_serve.add_argument("--no-scheduler", action="store_true",
                         help="Disable background stale-sweep / vacuum jobs")
    p_serve.set_defaults(func=_cmd_serve)

    p_demo = sub.add_parser("demo", help="Send a synthetic 3-agent A2A workflow to a running Skein")
    p_demo.add_argument("--endpoint", default="http://127.0.0.1:5050",
                        help="URL of a running Skein instance")
    p_demo.set_defaults(func=_cmd_demo)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
