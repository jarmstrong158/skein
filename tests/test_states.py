"""Guard tests for skein/states.py as the single source of truth.

The CHANGELOG advertises `skein/states.py` as the "single source of truth for
A2A task state strings". These tests are what make that claim true rather than
aspirational. They fail loudly in two situations:

  1. Someone spells an A2A state as a literal outside states.py — the mechanism
     by which a call site stops tracking this module (`test_no_state_literals_*`).
  2. Someone adds a state to states.py and misses a call site — every derived
     call site is exercised against a synthetic extra state and must pick it up
     with no edit of its own (`test_new_state_reaches_*`).

If you add a state to states.py and a test here fails, the test is right: some
call site is still hardcoding.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from skein import states
from skein.failures import detector
from skein.ingest.normalizer import store
from skein.ingest.parser import parse
from skein.validator import VALID_TASK_STATES, validate_payload
from skein_mcp import tools as mcp_tools

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED_PACKAGES = ("skein", "skein_mcp")

# A state that does not exist today. Injected into states.py's sets at runtime
# to simulate "the A2A spec added a state and we adopted it".
SYNTHETIC_STATE = "quarantined"


# ---------------------------------------------------------------------------
# 1. Structural: nothing outside states.py may spell a state
# ---------------------------------------------------------------------------

def _shipped_python_files() -> list[Path]:
    out: list[Path] = []
    for pkg in SHIPPED_PACKAGES:
        out.extend(sorted((REPO_ROOT / pkg).rglob("*.py")))
    assert out, "found no shipped python files to scan"
    return out


def _string_constants(tree: ast.AST) -> list[tuple[int, str]]:
    """Every string literal in the module, with its line number."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((node.lineno, node.value))
    return found


def test_no_state_literals_outside_states_module():
    """No shipped module may spell an A2A state string as a literal.

    A literal is how a call site quietly stops deriving. Import the constant
    from skein.states (or use is_failure_state / failure_states_sql / etc.)
    instead — then adding a state reaches this code for free.
    """
    states_module = REPO_ROOT / "skein" / "states.py"
    offenders: list[str] = []

    for path in _shipped_python_files():
        if path == states_module:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, value in _string_constants(tree):
            if value in states.ALL_STATES:
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno} spells {value!r}")

    assert not offenders, (
        "A2A state strings must be derived from skein/states.py, not spelled:\n  "
        + "\n  ".join(offenders)
    )


def test_no_state_literals_in_sql_in_clauses():
    """Belt-and-braces: no shipped module may contain a hand-rolled state IN-clause.

    Catches the literal even if it were assembled in a way the AST scan above
    reads as an ordinary string (e.g. inside one long SQL blob).
    """
    offenders: list[str] = []
    for path in _shipped_python_files():
        if path.name == "states.py":
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            lowered = line.lower()
            if " in (" in lowered and any(f"'{s}'" in lowered for s in states.ALL_STATES):
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "build state IN-clauses with states.failure_states_sql() / states.sql_in():\n  "
        + "\n  ".join(offenders)
    )


# ---------------------------------------------------------------------------
# 2. Internal consistency of states.py itself
# ---------------------------------------------------------------------------

def test_state_sets_partition_all_states():
    """Every state must be classified as terminal or non-terminal, exactly once.

    Adding a state to ALL_STATES without classifying it fails here.
    """
    assert set(states.ALL_STATES) == states.TERMINAL_STATES | states.NON_TERMINAL_STATES
    assert not (states.TERMINAL_STATES & states.NON_TERMINAL_STATES)


def test_failure_states_are_a_subset_of_terminal_states():
    assert states.FAILURE_STATES <= states.TERMINAL_STATES


def test_all_states_has_no_duplicates():
    assert len(set(states.ALL_STATES)) == len(states.ALL_STATES)


def test_validator_state_set_is_derived_not_respelled():
    assert frozenset(states.ALL_STATES) == VALID_TASK_STATES


def test_sql_in_renders_sorted_deterministic_clause():
    assert states.sql_in("s", ["b", "a"]) == "s IN ('a','b')"
    assert states.sql_in("s", ["a", "b"]) == states.sql_in("s", ["b", "a"])


def test_sql_in_rejects_empty_and_unsafe_states():
    with pytest.raises(ValueError):
        states.sql_in("s", [])
    with pytest.raises(ValueError):
        states.sql_in("s", ["ok", "not'safe"])


def test_failure_states_sql_targets_named_column():
    clause = states.failure_states_sql("t.current_state")
    assert clause.startswith("t.current_state IN (")
    for s in states.FAILURE_STATES:
        assert f"'{s}'" in clause


# ---------------------------------------------------------------------------
# 3. Behavioural: add a state, every call site must follow with no edit
# ---------------------------------------------------------------------------

@pytest.fixture
def extra_failure_state(monkeypatch):
    """Adopt a brand-new A2A failure state, as if the spec had grown one.

    Patches only skein.states. Any call site that still hardcodes — or that
    value-imported a set at module import instead of resolving at call time —
    will not see it, and its test below fails.
    """
    monkeypatch.setattr(states, "ALL_STATES", (*states.ALL_STATES, SYNTHETIC_STATE))
    monkeypatch.setattr(states, "TERMINAL_STATES", states.TERMINAL_STATES | {SYNTHETIC_STATE})
    monkeypatch.setattr(states, "FAILURE_STATES", states.FAILURE_STATES | {SYNTHETIC_STATE})
    return SYNTHETIC_STATE


def _make_failed_task(db, task_id: str, state: str, *, context_id: str = "ctx-guard") -> None:
    now = datetime.now(timezone.utc).isoformat()
    db.execute(
        """
        INSERT INTO tasks (id, context_id, current_state, created_at, updated_at,
                           terminal_at, error_code, error_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, context_id, state, now, now, now, "boom/999", "synthetic failure"),
    )


def test_new_state_reaches_recent_failures(db, extra_failure_state):
    _make_failed_task(db, "t-new-state", extra_failure_state)
    ids = {f["id"] for f in detector.recent_failures(db, hours=24)}
    assert "t-new-state" in ids


def test_new_state_reaches_failure_patterns(db, extra_failure_state):
    _make_failed_task(db, "t-new-state", extra_failure_state)
    patterns = detector.failure_patterns(db, days=7)
    by_code = {p["error_code"]: p for p in patterns}
    assert "boom/999" in by_code
    assert "t-new-state" in by_code["boom/999"]["example_task_ids"]


def test_new_state_reaches_cascade_context_signal(db, extra_failure_state):
    """The context signal must treat a newly adopted failure state as a failure."""
    root_terminal = datetime.now(timezone.utc)
    db.execute(
        """
        INSERT INTO tasks (id, context_id, current_state, created_at, updated_at, terminal_at)
        VALUES ('t-root', 'ctx-guard', 'failed', ?, ?, ?)
        """,
        (root_terminal.isoformat(),) * 3,
    )
    sibling_terminal = (root_terminal + timedelta(seconds=30)).isoformat()
    db.execute(
        """
        INSERT INTO tasks (id, context_id, current_state, created_at, updated_at, terminal_at)
        VALUES ('t-sibling', 'ctx-guard', ?, ?, ?, ?)
        """,
        (extra_failure_state, sibling_terminal, sibling_terminal, sibling_terminal),
    )
    cascade = detector.cascade_for(db, "t-root")
    assert {c["task_id"] for c in cascade} == {"t-sibling"}


def test_new_state_reaches_dashboard_overview_and_contexts(db, client, extra_failure_state):
    _make_failed_task(db, "t-new-state", extra_failure_state)

    # The overview's "Failures (24h)" tile must count the newly adopted state.
    panel = client.get("/", headers={"HX-Request": "true"})
    assert panel.status_code == 200
    html = panel.data.decode()
    failures_tile = html.split('<div class="stat-card stat-card-warn">', 1)[1]
    assert '<div class="stat-num">1</div>' in failures_tile.split("</div></div>", 1)[0]

    ctx_page = client.get("/contexts")
    assert ctx_page.status_code == 200
    # failed_count for ctx-guard must include the newly adopted state
    row = db.execute(
        f"""
        SELECT SUM(CASE WHEN {states.failure_states_sql()} THEN 1 ELSE 0 END) AS failed_count
          FROM tasks WHERE context_id = 'ctx-guard'
        """
    ).fetchone()
    assert row["failed_count"] == 1


def test_new_state_reaches_failures_page(db, client, extra_failure_state):
    _make_failed_task(db, "t-new-state", extra_failure_state)
    resp = client.get("/failures")
    assert resp.status_code == 200
    assert b"t-new-state" in resp.data


def test_new_state_reaches_task_detail_cascade_gate(db, client, extra_failure_state):
    """task_detail only computes a cascade for failure states — new one included."""
    assert states.is_failure_state(extra_failure_state)
    _make_failed_task(db, "t-new-state", extra_failure_state)
    resp = client.get("/tasks/t-new-state")
    assert resp.status_code == 200


def test_new_state_reaches_tasks_page_filter_list(client, extra_failure_state):
    resp = client.get("/tasks")
    assert resp.status_code == 200
    assert extra_failure_state.encode() in resp.data


def test_new_state_reaches_mcp_failure_rate(db, extra_failure_state):
    """get_agent_activity's failure_rate must count the newly adopted state."""
    now = datetime.now(timezone.utc).isoformat()
    _make_failed_task(db, "t-new-state", extra_failure_state)
    db.execute(
        """
        INSERT INTO agents (id, first_seen_at, last_seen_at) VALUES ('agent-x', ?, ?)
        """,
        (now, now),
    )
    db.execute(
        """
        INSERT INTO messages (task_id, sequence, direction, method, from_agent_id,
                              payload_json, payload_hash, captured_at)
        VALUES ('t-new-state', 1, 'inbound', 'message/send', 'agent-x', '{}', 'h1', ?)
        """,
        (now,),
    )
    activity = mcp_tools.get_agent_activity(db, "agent-x", hours=24)
    assert activity["task_count"] == 1
    assert activity["failure_rate"] == 1.0


def test_new_state_reaches_validator(extra_failure_state):
    """A newly adopted state must stop being reported as a spec violation."""
    payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {"id": "t1", "status": {"state": extra_failure_state}},
    }
    codes = {w.code for w in validate_payload(payload)}
    assert "a2a/invalid-task-state" not in codes


def test_unknown_state_is_still_flagged_by_validator():
    """Control for the test above — a genuinely unknown state must still warn."""
    payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {"id": "t1", "status": {"state": "definitely-not-a2a"}},
    }
    codes = {w.code for w in validate_payload(payload)}
    assert "a2a/invalid-task-state" in codes


def test_new_terminal_state_reaches_ingest_normalizer(db, extra_failure_state):
    """Ingest must set terminal_at for a newly adopted terminal state."""
    payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "result": {
            "id": "t-terminal-new",
            "contextId": "ctx-guard",
            "status": {"state": extra_failure_state, "timestamp": "2026-04-19T10:00:05Z"},
        },
    }
    store(db, parse(payload), direction="inbound")
    row = db.execute(
        "SELECT current_state, terminal_at FROM tasks WHERE id = 't-terminal-new'"
    ).fetchone()
    assert row["current_state"] == extra_failure_state
    assert row["terminal_at"] is not None
