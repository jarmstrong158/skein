"""Dashboard blueprint: server-rendered Jinja with HTMX for partial refreshes."""

from __future__ import annotations

import json

from flask import Blueprint, abort, jsonify, render_template, request

from ..db import get_db
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
    conn = get_db()
    state = request.args.get("state")
    agent = request.args.get("agent")
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
    states = ["submitted", "working", "input-required", "completed", "failed", "canceled", "rejected"]
    return render_template("tasks.html", tasks=rows, states=states, current_state=state, current_agent=agent)


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

    return render_template(
        "task_detail.html",
        timeline=timeline,
        agents_map=agents_map,
        json=json,
    )
