"""A2A task lifecycle state constants.

Single source of truth for state strings — used by the parser, normalizer,
failure detector, dashboard, MCP tools, and validator. Per the A2A spec.

Nothing outside this module may spell an A2A state as a literal. SQL call
sites build their `IN (...)` clauses with :func:`failure_states_sql` (and
:func:`sql_in` generally) and membership checks go through
:func:`is_failure_state` / :func:`is_terminal_state`. Those helpers read the
module-level sets *at call time*, so adding a state here reaches every call
site without editing it — and `tests/test_states.py` fails loudly if some
call site stops deriving.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

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

# States are code-owned constants, never user input — but rendering anything
# into SQL text deserves a shape check, so a future state string can never
# become an injection vector.
_SAFE_STATE_RE = re.compile(r"[a-z][a-z0-9-]*")


def sql_in(column: str, states: Iterable[str]) -> str:
    """Render a `<column> IN ('a','b',...)` SQL fragment from state constants.

    Sorted for deterministic SQL text (stable query plans and stable tests).
    """
    values = sorted(states)
    if not values:
        raise ValueError("sql_in() needs at least one state")
    for v in values:
        if not _SAFE_STATE_RE.fullmatch(v):
            raise ValueError(f"state {v!r} is not safe to render into SQL")
    rendered = ",".join(f"'{v}'" for v in values)
    return f"{column} IN ({rendered})"


def failure_states_sql(column: str = "current_state") -> str:
    """`<column> IN (...)` over FAILURE_STATES, resolved at call time."""
    return sql_in(column, FAILURE_STATES)


def is_failure_state(state: str | None) -> bool:
    """True if `state` is one of the A2A failure states, resolved at call time."""
    return state in FAILURE_STATES


def is_terminal_state(state: str | None) -> bool:
    """True if `state` is one of the A2A terminal states, resolved at call time."""
    return state in TERMINAL_STATES


def all_states() -> tuple[str, ...]:
    """Every A2A state, in spec order, resolved at call time.

    Prefer this over importing ALL_STATES by value anywhere that renders or
    iterates the list at runtime — a value-import snapshots at module import
    and silently stops tracking this module.
    """
    return ALL_STATES


def is_valid_state(state: str | None) -> bool:
    """True if `state` is a state the A2A spec defines, resolved at call time."""
    return state in ALL_STATES
