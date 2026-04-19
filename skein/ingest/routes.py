"""Flask blueprint for ingest endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from ..db import get_db
from .normalizer import store, upsert_agent_card
from .parser import ParseError, _parse_traceparent, parse

bp = Blueprint("ingest", __name__, url_prefix="/trace")


@bp.post("/ingest")
def ingest():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400
    payload = body.get("payload")
    if not isinstance(payload, dict):
        return jsonify({"error": "missing or invalid 'payload' field"}), 400
    direction = body.get("direction", "inbound")
    if direction not in ("inbound", "outbound"):
        return jsonify({"error": "direction must be 'inbound' or 'outbound'"}), 400
    captured_at = body.get("captured_at") or datetime.now(timezone.utc).isoformat()
    protocol_version = body.get("protocol_version")

    try:
        event = parse(payload, protocol_version=protocol_version)
    except ParseError as e:
        return jsonify({"error": f"parse error: {e}"}), 400

    # If the caller forwarded the HTTP `traceparent` header (via the body's
    # top-level `traceparent` field), honor it when the JSON-RPC payload
    # itself didn't carry trace context inside metadata.
    body_tp = body.get("traceparent")
    if isinstance(body_tp, str) and not event.message.traceparent:
        tid, sid = _parse_traceparent(body_tp)
        if tid:
            event.message.traceparent = body_tp
            event.message.trace_id = tid
            event.message.span_id = sid

    conn = get_db()
    try:
        result = store(conn, event, direction=direction, captured_at=captured_at)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(result), 201


@bp.post("/agent_card")
def agent_card():
    card = request.get_json(silent=True)
    if not isinstance(card, dict):
        return jsonify({"error": "body must be an agent card JSON object"}), 400
    conn = get_db()
    try:
        agent_id = upsert_agent_card(conn, card)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"agent_id": agent_id}), 201


@bp.get("/health")
def health():
    conn = get_db()
    msg_24h = conn.execute(
        "SELECT COUNT(*) AS c FROM messages WHERE captured_at > datetime('now', '-1 day')"
    ).fetchone()["c"]
    db_path = current_app.config["SKEIN_CONFIG"].db_path
    import os
    size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 3) if os.path.exists(db_path) else 0
    return jsonify({"status": "ok", "db_size_mb": size_mb, "message_count_24h": msg_24h})
