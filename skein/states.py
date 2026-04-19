"""A2A task lifecycle state constants.

Single source of truth for state strings — used by the parser, normalizer,
failure detector, dashboard, and validator. Per the A2A spec.
"""

from __future__ import annotations

# Non-terminal states
SUBMITTED = "submitted"
WORKING = "working"
INPUT_REQUIRED = "input-required"

# Terminal states
COMPLETED = "completed"
FAILED = "failed"
CANCELED = "canceled"
REJECTED = "rejected"

ALL_STATES: tuple[str, ...] = (
    SUBMITTED, WORKING, INPUT_REQUIRED,
    COMPLETED, FAILED, CANCELED, REJECTED,
)

TERMINAL_STATES: frozenset[str] = frozenset({COMPLETED, FAILED, CANCELED, REJECTED})
FAILURE_STATES: frozenset[str] = frozenset({FAILED, CANCELED, REJECTED})
NON_TERMINAL_STATES: frozenset[str] = frozenset({SUBMITTED, WORKING, INPUT_REQUIRED})
