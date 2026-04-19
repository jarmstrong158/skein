"""Dashboard blueprint: server-rendered Jinja with HTMX for partial refreshes."""

from __future__ import annotations

import json

from flask import Blueprint, abort, jsonify, render_template, request

from ..db import get_db
from ..failures.detector import cascade_for, failure_patterns, recent_failures
from ..timeline.builder import build, to_dict

bp = Blueprint(
    "dashboard",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/dashboard-static",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_htmx() -> bool:
    return request.headers.get("HX-Request") == "true"


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@bp.get("/")
def overview():
    conn = get_db()
    counts = {
        "active_tasks": conn.execute(
            "SELECT COUNT(*) AS c FROM tasks WHERE terminal_at IS NULL"
        ).fetchone()["c"],
        "failed_24h": conn.execute(
            """
            SELECT COUNT(*) AS c FROM tasks
             WHERE current_state IN ('failed','rejected','canceled')
               AND updated_at > datetime('now', '-1 day')
            """
        ).fetchone()["c"],
        "agents_seen": conn.execute("SELECT COUNT(*) AS c FROM agents").fetchone()["c"],
        "messages_24h": conn.execute(
            "SELECT COUNT(*) AS c FROM messages WHERE captured_at > datetime('now', '-1 day')"
        ).fetchone()["c"],
        "spec_warnings_24h": conn.execute(
            "SELECT COUNT(*) AS c FROM spec_warnings WHERE raised_at > datetime('now', '-1 day')"
        ).fetchone()["c"],
    }
    recent = conn.execute(
        """
        SELECT t.id, t.current_state, t.updated_at, t.context_id,
               (SELECT COUNT(*) FROM messages m WHERE m.task_id = t.id) AS message_count
          FROM tasks t
         ORDER BY t.updated_at DESC
         LIMIT 15
        """
    ).fetchall()
    if _is_htmx():
        return render_template("_overview_panel.html", counts=counts, recent=recent)
    return render_template("overview.html", counts=counts, recent=recent)


@bp.get("/contexts")
def contexts():
    """List A2A contextIds with task counts and aggregate state info.

    A contextId groups tasks/messages into one logical conversation, per the
    A2A spec. This view is the primary way to browse "the whole conversation".
    """
    conn = get_db()
    rows = conn.execute(
        """
        SELECT context_id,
               COUNT(*)                                          AS task_count,
               SUM(CASE WHEN current_state IN ('failed','rejected','canceled') THEN 1 ELSE 0 END)
                                                                 AS failed_count,
               SUM(CASE WHEN terminal_at IS NULL THEN 1 ELSE 0 END)
                                                                 AS active_count,
               MIN(created_at)                                   AS started_at,
               MAX(updated_at)                                   AS last_activity_at
          FROM tasks
         WHERE context_id IS NOT NULL
         GROUP BY context_id
         ORDER BY MAX(updated_at) DESC
         LIMIT 200
        """
    ).fetchall()
    return render_template("contexts.html", contexts=rows)


@bp.get("/contexts/<context_id>")
def context_detail(context_id: str):
    conn = get_db()
    tasks_in_ctx = conn.execute(
        """
        SELECT t.id, t.current_state, t.created_at, t.updated_at, t.error_code,
               (SELECT COUNT(*) FROM messages m WHERE m.task_id = t.id) AS message_count
          FROM tasks t
         WHERE t.context_id = ?
         ORDER BY t.created_at
        """,
        (context_id,),
    ).fetchall()
    if not tasks_in_ctx:
        abort(404)

    # Pull every message in the context, ordered chronologically across tasks,
    # so we render one merged conversation timeline.
    msgs = conn.execute(
        """
        SELECT m.id, m.task_id, m.sequence, m.direction, m.method,
               m.from_agent_id, m.to_agent_id,
               m.captured_at, m.occurred_at,
               m.trace_id, t.current_state AS task_state
          FROM messages m
          JOIN tasks t ON t.id = m.task_id
         WHERE t.context_id = ?
         ORDER BY COALESCE(m.occurred_at, m.captured_at), m.id
        """,
        (context_id,),
    ).fetchall()

    agent_ids = {m["from_agent_id"] for m in msgs if m["from_agent_id"]} | {
        m["to_agent_id"] for m in msgs if m["to_agent_id"]
    }
    agents_map: dict[str, str] = {}
    if agent_ids:
        placeholders = ",".join("?" for _ in agent_ids)
        for r in conn.execute(
            f"SELECT id, name FROM agents WHERE id IN ({placeholders})", list(agent_ids)
        ).fetchall():
            agents_map[r["id"]] = r["name"] or r["id"]

    return render_template(
        "context_detail.html",
        context_id=context_id,
        tasks=tasks_in_ctx,
        messages=msgs,
        agents_map=agents_map,
    )


@bp.get("/agents")
def agents():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT a.id, a.name, a.endpoint_url, a.last_seen_at, a.first_seen_at,
               (SELECT COUNT(*) FROM messages m
                 WHERE m.from_agent_id = a.id OR m.to_agent_id = a.id) AS message_count
          FROM agents a
         ORDER BY a.last_seen_at DESC
        """
    ).fetchall()
    return render_template("agents.html", agents=rows)


@bp.get("/tasks")
def tasks():
    from ..states import ALL_STATES
    conn = get_db()
    state = request.args.get("state")
    agent = request.args.get("agent")
    q = (request.args.get("q") or "").strip()
    where = []
    params: list = []
    if state:
        where.append("t.current_state = ?")
        params.append(state)
    if agent:
        where.append(
            "EXISTS (SELECT 1 FROM messages m WHERE m.task_id = t.id "
            "AND (m.from_agent_id = ? OR m.to_agent_id = ?))"
        )
        params.extend([agent, agent])
    if q:
        # Free-text search across task id, context id, error fields, and
        # the raw payload bodies of messages on the task. Cheap LIKE scan;
        # adequate for local-tool scale.
        where.append(
            "(t.id LIKE ? OR t.context_id LIKE ? OR t.error_code LIKE ? "
            "OR t.error_message LIKE ? OR EXISTS ("
            "  SELECT 1 FROM messages m WHERE m.task_id = t.id "
            "    AND m.payload_json LIKE ?))"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like, like])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = conn.execute(
        f"""
        SELECT t.id, t.context_id, t.current_state, t.created_at, t.updated_at,
               t.terminal_at, t.error_code,
               (SELECT COUNT(*) FROM messages m WHERE m.task_id = t.id) AS message_count
          FROM tasks t
          {where_sql}
         ORDER BY t.updated_at DESC
         LIMIT 200
        """,
        params,
    ).fetchall()
    if _is_htmx():
        return render_template("_tasks_table.html", tasks=rows)
    return render_template(
        "tasks.html",
        tasks=rows,
        states=list(ALL_STATES),
        current_state=state,
        current_agent=agent,
        current_q=q,
    )


@bp.get("/tasks/<task_id>")
def task_detail(task_id: str):
    conn = get_db()
    timeline = build(conn, task_id)
    if timeline is None:
        abort(404)

    if request.args.get("format") == "json":
        return jsonify(to_dict(timeline))

    # Resolve agent names for display
    agent_ids = set()
    for e in timeline.events:
        if e.kind == "message":
            for k in ("from_agent_id", "to_agent_id"):
                if e.data.get(k):
                    agent_ids.add(e.data[k])
    agents_map: dict[str, str] = {}
    if agent_ids:
        placeholders = ",".join("?" for _ in agent_ids)
        for r in conn.execute(
            f"SELECT id, name FROM agents WHERE id IN ({placeholders})", list(agent_ids)
        ).fetchall():
            agents_map[r["id"]] = r["name"] or r["id"]

    cascade = []
    if timeline.task and timeline.task.get("current_state") in ("failed", "rejected", "canceled"):
        cascade = cascade_for(conn, task_id)

    spec_warnings = conn.execute(
        """
        SELECT severity, code, description, field_path, message_id, raised_at
          FROM spec_warnings WHERE task_id = ?
         ORDER BY id
        """,
        (task_id,),
    ).fetchall()

    return render_template(
        "task_detail.html",
        timeline=timeline,
        agents_map=agents_map,
        cascade=cascade,
        spec_warnings=spec_warnings,
        json=json,
    )


@bp.get("/spec-warnings")
def spec_warnings():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT w.id, w.severity, w.code, w.description, w.field_path,
               w.task_id, w.message_id, w.agent_id, w.raised_at
          FROM spec_warnings w
         ORDER BY w.raised_at DESC
         LIMIT 200
        """
    ).fetchall()
    by_code = conn.execute(
        """
        SELECT code, severity, COUNT(*) AS c
          FROM spec_warnings
         GROUP BY code, severity
         ORDER BY c DESC
        """
    ).fetchall()
    return render_template("spec_warnings.html", warnings=rows, by_code=by_code)


@bp.get("/failures")
def failures():
    conn = get_db()
    hours = int(request.args.get("hours", "24"))
    days = int(request.args.get("days", "7"))
    return render_template(
        "failures.html",
        recent=recent_failures(conn, hours=hours, limit=100),
        patterns=failure_patterns(conn, days=days),
        hours=hours,
        days=days,
    )
