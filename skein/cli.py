"""Command-line interface for Skein."""

from __future__ import annotations

import argparse
import sys

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
        console.print("[dim]scheduler started (stale_sweep every 60s)[/dim]")
    console.print(f"[bold green]Skein[/bold green] serving at [bold]http://{cfg.host}:{cfg.port}[/bold]")
    app.run(host=cfg.host, port=cfg.port, debug=False, use_reloader=False)
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    """Run a self-contained multi-agent A2A toy workflow against a Skein endpoint.

    No real agents, no a2a-sdk needed — just synthetic JSON-RPC payloads
    that exercise every part of the Skein store: success path, explicit
    failure, cascade, stale task, OTLP trace propagation, spec violations,
    and multiple parallel contexts.
    """
    from ._demo_data import build_scenarios
    from .sdk import client as sdk_client  # internal helper, not public API

    client = sdk_client.install(endpoint=args.endpoint, raise_on_error=False)
    console.print(f"[bold]Skein demo[/bold] -> {args.endpoint}")

    scenarios = build_scenarios()

    for card in scenarios.agent_cards:
        client.send_agent_card(card)
    console.print(f"  registered [cyan]{len(scenarios.agent_cards)}[/cyan] agents")

    for entry in scenarios.events:
        client.send(entry["payload"], direction=entry["direction"])

    for note in scenarios.summary_lines:
        console.print("  " + note)

    console.print(
        f"\n[bold]Open[/bold] [cyan]{args.endpoint}[/cyan] to inspect.\n"
        f"  * Overview / Tasks / Contexts / Failures / Spec warnings show all the above\n"
        f"  * Task detail pages surface cascades, OTLP trace IDs, and per-task spec warnings\n"
        f"  * Stuck tasks will be marked failed by the stale-sweep within ~60s"
    )
    return 0


def _cmd_clean(args: argparse.Namespace) -> int:
    from .config import Config
    from .db import open_db
    from .retention import clean_older_than, parse_duration

    cfg = Config.load(args.config)
    try:
        delta = parse_duration(args.older_than)
    except ValueError as e:
        console.print(f"[red]error:[/red] {e}")
        return 2

    if args.dry_run:
        from datetime import datetime, timezone
        cutoff = (datetime.now(timezone.utc) - delta).isoformat()
        conn = open_db(cfg.db_path)
        try:
            n = conn.execute(
                "SELECT COUNT(*) AS c FROM tasks WHERE terminal_at IS NOT NULL AND updated_at < ?",
                (cutoff,),
            ).fetchone()["c"]
            m = conn.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE task_id IN "
                "(SELECT id FROM tasks WHERE terminal_at IS NOT NULL AND updated_at < ?)",
                (cutoff,),
            ).fetchone()["c"]
        finally:
            conn.close()
        console.print(
            f"[yellow]dry-run:[/yellow] would delete {n} task(s) and {m} message(s) "
            f"older than {args.older_than} (cutoff {cutoff})"
        )
        return 0

    conn = open_db(cfg.db_path)
    try:
        result = clean_older_than(conn, older_than=delta)
    finally:
        conn.close()
    console.print(
        f"[bold]Cleaned[/bold] tasks older than {args.older_than} (cutoff {result.cutoff_iso}):\n"
        f"  tasks:        {result.tasks_deleted}\n"
        f"  messages:     {result.messages_deleted}\n"
        f"  transitions:  {result.transitions_deleted}\n"
        f"  artifacts:    {result.artifacts_deleted}\n"
        f"  refs:         {result.refs_deleted}\n"
        f"  spec warnings:{result.warnings_deleted}"
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

    p_clean = sub.add_parser("clean", help="Delete terminal tasks older than a cutoff")
    p_clean.add_argument("--older-than", default="7d",
                         help="Cutoff age, e.g. '7d', '12h', '30m' (default: 7d)")
    p_clean.add_argument("--config", default="./config.json")
    p_clean.add_argument("--dry-run", action="store_true",
                         help="Report what would be deleted without modifying the DB")
    p_clean.set_defaults(func=_cmd_clean)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
