"""Passive A2A spec compliance checks raised at ingest time.

Distinct from operational failures: a spec warning says "the message itself
violated the A2A spec", not "the agent's work failed". Warnings are stored
in the spec_warnings table and surfaced separately in the dashboard.

Designed to be conservative — only flag things the A2A spec actually
requires. Permissive on optional fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .states import ALL_STATES, is_valid_state

# Derived, never re-spelled: adding a state to skein/states.py teaches the
# validator about it automatically. Membership is checked through
# is_valid_state() so the lookup resolves at call time rather than snapshotting
# this frozenset at import. See tests/test_states.py.
VALID_TASK_STATES: frozenset[str] = frozenset(ALL_STATES)

VALID_AGENT_CARD_REQUIRED = ("name", "url", "version")


@dataclass
class SpecWarning:
    severity: str        # 'warning' | 'error'
    code: str            # e.g. 'a2a/missing-required-field'
    description: str
    field_path: str | None = None


# ---------------------------------------------------------------------------
# Payload validators (run by ingest layer over each parsed payload)
# ---------------------------------------------------------------------------

def validate_payload(payload: dict[str, Any]) -> list[SpecWarning]:
    """Return any spec warnings for a single A2A JSON-RPC payload."""
    warnings: list[SpecWarning] = []

    # JSON-RPC envelope
    if payload.get("jsonrpc") != "2.0":
        warnings.append(SpecWarning(
            severity="warning",
            code="jsonrpc/wrong-version",
            description=f"jsonrpc must be '2.0', got {payload.get('jsonrpc')!r}",
            field_path="jsonrpc",
        ))
    if "id" not in payload and "method" in payload:
        warnings.append(SpecWarning(
            severity="warning",
            code="jsonrpc/missing-request-id",
            description="JSON-RPC request is missing the 'id' field",
            field_path="id",
        ))

    # Task state in result
    result = payload.get("result")
    if isinstance(result, dict):
        status = result.get("status")
        if isinstance(status, dict):
            state = status.get("state")
            if state is not None and not is_valid_state(state):
                warnings.append(SpecWarning(
                    severity="warning",
                    code="a2a/invalid-task-state",
                    description=f"Task state {state!r} is not one of A2A's defined states",
                    field_path="result.status.state",
                ))

    # Status-update events
    if isinstance(result, dict) and result.get("kind") == "status-update" and "taskId" not in result:
        warnings.append(SpecWarning(
                severity="error",
                code="a2a/status-update-missing-task-id",
                description="status-update event is missing required 'taskId'",
                field_path="result.taskId",
            ))

    # Message in params
    params = payload.get("params")
    if isinstance(params, dict):
        msg = params.get("message")
        if isinstance(msg, dict):
            if "messageId" not in msg:
                warnings.append(SpecWarning(
                    severity="warning",
                    code="a2a/message-missing-id",
                    description="A2A Message is missing 'messageId'",
                    field_path="params.message.messageId",
                ))
            if "role" not in msg:
                warnings.append(SpecWarning(
                    severity="warning",
                    code="a2a/message-missing-role",
                    description="A2A Message is missing 'role'",
                    field_path="params.message.role",
                ))
            parts = msg.get("parts")
            if not isinstance(parts, list) or not parts:
                warnings.append(SpecWarning(
                    severity="warning",
                    code="a2a/message-missing-parts",
                    description="A2A Message must have a non-empty 'parts' array",
                    field_path="params.message.parts",
                ))

    return warnings


# ---------------------------------------------------------------------------
# Agent card validator (run on POST /trace/agent_card)
# ---------------------------------------------------------------------------

def validate_agent_card(card: dict[str, Any]) -> list[SpecWarning]:
    warnings: list[SpecWarning] = []
    for required in VALID_AGENT_CARD_REQUIRED:
        if required not in card:
            warnings.append(SpecWarning(
                severity="warning",
                code="a2a/agent-card-missing-required-field",
                description=f"Agent card is missing required field {required!r}",
                field_path=required,
            ))
    return warnings
