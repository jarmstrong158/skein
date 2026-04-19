"""Parse A2A JSON-RPC payloads into a normalized intermediate representation.

The parser is permissive: unknown fields are preserved in `extra`, unknown
methods produce a ParsedEvent with method set but minimal extracted detail.
This keeps ingest robust as the A2A spec evolves.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from ..states import TERMINAL_STATES  # re-export for back-compat

__all_terminal = TERMINAL_STATES  # noqa: F841 (kept so existing imports keep working)


@dataclass
class ParsedTask:
    id: str
    context_id: str | None = None
    state: str | None = None
    state_timestamp: str | None = None  # ISO8601 from payload, or None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class ParsedMessage:
    method: str
    payload: dict[str, Any]
    from_agent_id: str | None = None
    to_agent_id: str | None = None
    reference_task_ids: list[str] = field(default_factory=list)
    occurred_at: str | None = None  # ISO8601 if asserted by client
    # W3C Trace Context — extracted from a2a Message/Task metadata. The
    # ingest body's top-level `traceparent` (set by SDKs that captured the
    # HTTP header) is layered in by the route handler before storage.
    trace_id: str | None = None
    span_id: str | None = None
    traceparent: str | None = None


@dataclass
class ParsedArtifact:
    name: str | None
    mime_type: str | None
    content_text: str | None
    bytes: int | None
    produced_at: str | None


@dataclass
class ParsedEvent:
    """Normalized view of one ingested payload."""
    task: ParsedTask | None
    message: ParsedMessage
    artifacts: list[ParsedArtifact] = field(default_factory=list)
    protocol_version: str | None = None


class ParseError(ValueError):
    """Raised when a payload is structurally invalid (not just unknown)."""


def payload_hash(payload: dict[str, Any]) -> str:
    """Stable hash for deduplication. Sorted keys, no whitespace."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _extract_task_from_result(result: dict[str, Any]) -> ParsedTask | None:
    """A2A `result` for tasks/get and message/send (when task is returned)."""
    if not isinstance(result, dict):
        return None
    # A2A Task object: {id, contextId, status: {state, timestamp}, ...}
    if "id" in result and "status" in result:
        status = result.get("status") or {}
        return ParsedTask(
            id=result["id"],
            context_id=result.get("contextId"),
            state=status.get("state") if isinstance(status, dict) else None,
            state_timestamp=status.get("timestamp") if isinstance(status, dict) else None,
        )
    return None


def _extract_task_from_message_params(params: dict[str, Any]) -> ParsedTask | None:
    """For message/send requests, the message itself may carry taskId/contextId."""
    if not isinstance(params, dict):
        return None
    msg = params.get("message") or {}
    task_id = msg.get("taskId") or params.get("taskId")
    if not task_id:
        return None
    return ParsedTask(
        id=task_id,
        context_id=msg.get("contextId") or params.get("contextId"),
        state="submitted",  # implied: client is sending into this task
    )


_TRACEPARENT_RE = None  # populated lazily; format defined in W3C Trace Context


def _parse_traceparent(tp: str) -> tuple[str | None, str | None]:
    """Return (trace_id, span_id) extracted from a W3C traceparent header.

    Format: '<version>-<trace-id-32hex>-<span-id-16hex>-<flags>'
    Returns (None, None) if malformed; we never raise.
    """
    if not isinstance(tp, str):
        return None, None
    parts = tp.strip().split("-")
    if len(parts) != 4:
        return None, None
    _, trace_id, span_id, _ = parts
    if len(trace_id) != 32 or len(span_id) != 16:
        return None, None
    return trace_id, span_id


def _extract_trace_context(payload: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Extract (trace_id, span_id, traceparent) from a2a metadata fields.

    Looks in payload.params.message.metadata, payload.result.metadata, and
    payload.params.metadata. First match wins. Honors both an explicit
    `traceparent` string and split `trace_id`/`span_id` keys.
    """
    candidates: list[dict[str, Any]] = []
    params = payload.get("params")
    if isinstance(params, dict):
        msg = params.get("message")
        if isinstance(msg, dict) and isinstance(msg.get("metadata"), dict):
            candidates.append(msg["metadata"])
        if isinstance(params.get("metadata"), dict):
            candidates.append(params["metadata"])
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("metadata"), dict):
        candidates.append(result["metadata"])

    for meta in candidates:
        tp = meta.get("traceparent")
        if isinstance(tp, str):
            tid, sid = _parse_traceparent(tp)
            if tid:
                return tid, sid, tp
        tid = meta.get("trace_id") or meta.get("traceId")
        sid = meta.get("span_id") or meta.get("spanId")
        if isinstance(tid, str):
            return tid, (sid if isinstance(sid, str) else None), None
    return None, None, None


def _extract_reference_task_ids(payload: dict[str, Any]) -> list[str]:
    """Pull referenceTaskIds from a Message object wherever it appears."""
    refs: list[str] = []
    # In request params
    msg = (payload.get("params") or {}).get("message") if isinstance(payload.get("params"), dict) else None
    if isinstance(msg, dict):
        refs.extend(msg.get("referenceTaskIds") or [])
    # In result (when result is itself a Message)
    result = payload.get("result")
    if isinstance(result, dict):
        refs.extend(result.get("referenceTaskIds") or [])
    return [r for r in refs if isinstance(r, str)]


def _extract_artifacts(result: dict[str, Any] | None) -> list[ParsedArtifact]:
    """Pull artifacts off a Task result, if present."""
    if not isinstance(result, dict):
        return []
    arts = result.get("artifacts") or []
    out: list[ParsedArtifact] = []
    if not isinstance(arts, list):
        return out
    for a in arts:
        if not isinstance(a, dict):
            continue
        # A2A artifact: {name, parts: [{kind, text|data|file}]}
        text_parts = []
        for p in a.get("parts") or []:
            if isinstance(p, dict) and p.get("kind") == "text":
                text_parts.append(str(p.get("text", "")))
        content_text = "\n".join(text_parts) if text_parts else None
        out.append(
            ParsedArtifact(
                name=a.get("name"),
                mime_type=a.get("mimeType"),
                content_text=content_text,
                bytes=len(content_text.encode()) if content_text else None,
                produced_at=None,
            )
        )
    return out


def parse(payload: dict[str, Any], *, protocol_version: str | None = None) -> ParsedEvent:
    """Parse one A2A JSON-RPC payload into a ParsedEvent.

    Accepts both request (method+params) and response (result/error) shapes.
    """
    if not isinstance(payload, dict):
        raise ParseError("payload must be a JSON object")
    if "jsonrpc" not in payload:
        raise ParseError("missing jsonrpc field")

    method = payload.get("method")
    raw_params = payload.get("params")
    params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
    raw_result = payload.get("result")
    result: dict[str, Any] | None = raw_result if isinstance(raw_result, dict) else None
    raw_error = payload.get("error")
    error: dict[str, Any] | None = raw_error if isinstance(raw_error, dict) else None

    # Determine effective method: requests carry it; responses inherit from context
    # but we may not know it. Default to "response" if absent.
    effective_method = method or ("response" if (result is not None or error is not None) else "unknown")

    # Try to extract a task identity from any of the standard locations.
    task: ParsedTask | None = None
    if result is not None:
        task = _extract_task_from_result(result)
    if task is None and method in ("message/send", "message/stream", "tasks/sendSubscribe"):
        task = _extract_task_from_message_params(params)
    if task is None and method == "tasks/get":
        task_id = params.get("id") or params.get("taskId")
        if task_id:
            task = ParsedTask(id=task_id)

    # Status update events (streaming): result has {kind: "status-update", taskId, status}
    if task is None and isinstance(result, dict) and result.get("kind") == "status-update":
        status = result.get("status") or {}
        task = ParsedTask(
            id=result.get("taskId") or "",
            context_id=result.get("contextId"),
            state=status.get("state") if isinstance(status, dict) else None,
            state_timestamp=status.get("timestamp") if isinstance(status, dict) else None,
        )

    # Errors on a known-task response should be flagged on the task.
    if error and task is not None:
        task.error_code = str(error.get("code", ""))
        task.error_message = str(error.get("message", ""))
        if task.state is None:
            task.state = "failed"

    # Sender/recipient agent ids — A2A doesn't always carry these; capture if present.
    from_agent = None
    to_agent = None
    msg = params.get("message") if isinstance(params, dict) else None
    if isinstance(msg, dict):
        from_agent = msg.get("agentId") or msg.get("fromAgentId")
        to_agent = params.get("toAgentId") if isinstance(params, dict) else None

    occurred_at = None
    if isinstance(msg, dict):
        occurred_at = msg.get("timestamp")
    if occurred_at is None and isinstance(result, dict):
        status = result.get("status")
        if isinstance(status, dict):
            occurred_at = status.get("timestamp")

    trace_id, span_id, traceparent = _extract_trace_context(payload)
    parsed_msg = ParsedMessage(
        method=effective_method,
        payload=payload,
        from_agent_id=from_agent,
        to_agent_id=to_agent,
        reference_task_ids=_extract_reference_task_ids(payload),
        occurred_at=occurred_at,
        trace_id=trace_id,
        span_id=span_id,
        traceparent=traceparent,
    )

    return ParsedEvent(
        task=task,
        message=parsed_msg,
        artifacts=_extract_artifacts(result),
        protocol_version=protocol_version,
    )
