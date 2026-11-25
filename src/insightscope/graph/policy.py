"""Routing decisions, as pure functions of state.

Deliberately imports nothing from LangGraph and nothing that can call a model. Every
rule about retries, budgets, and degradation lives here, in code, where it can be
tested with a dictionary and reviewed in a diff.
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from insightscope.contracts.report import Issue
from insightscope.graph.state import AuditState

Route = Literal[
    "critique",
    "repair_synthesis",
    "repair_extraction",
    "finalize",
    "finalize_caveats",
    "escalate",
]

ACTIONABLE = ("blocker", "major")


def count_attempts(state: AuditState, node: str) -> int:
    """How many times this node has run. The ledger is the single source of truth."""
    return sum(1 for attempt in state.get("attempts", ()) if attempt.node == node)


def has_fatal(state: AuditState) -> bool:
    return bool(state.get("fatal"))


def budget_left(state: AuditState, node: str) -> bool:
    config = state["config"]
    return count_attempts(state, node) < config.loop.max_node_attempts


def actionable(issues: tuple[Issue, ...] | list[Issue]) -> list[Issue]:
    return [issue for issue in issues if issue.severity in ACTIONABLE]


def choose_repair_target(issues: list[Issue]) -> Literal["extract", "synthesize"]:
    """Which node owns the defect.

    Ties go to synthesis: it is the cheaper repair, and a report worded badly is more
    common than extraction being wrong twice in a row.
    """
    counts = Counter(issue.target for issue in issues)
    return "extract" if counts["extract"] > counts["synthesize"] else "synthesize"


def route_after_validate(state: AuditState) -> Route:
    """Deterministic validation runs first. No point paying a critic for what code proved."""
    if has_fatal(state):
        return "escalate"

    validation = state.get("validation")
    if validation is None:
        return "finalize_caveats"
    if validation.ok:
        return "critique"

    if budget_left(state, "synthesize"):
        return "repair_synthesis"
    return "finalize_caveats"


def route_after_critique(state: AuditState) -> Route:
    """The critic may ask for a rewrite. It may never ask for an assertion."""
    if has_fatal(state):
        return "escalate"

    critique = state.get("critique")
    if critique is None:
        return "finalize_caveats"
    if critique.verdict == "accept":
        return "finalize"

    issues = actionable(critique.issues)
    if not issues:
        # Only minor complaints left: report them, do not spin on them.
        return "finalize_caveats"

    config = state["config"]
    if state.get("cycle", 0) >= config.loop.max_repair_cycles:
        return "finalize_caveats"

    target = choose_repair_target(issues)
    node = "extract_claims" if target == "extract" else "synthesize"
    if not budget_left(state, node):
        return "finalize_caveats"

    return "repair_extraction" if target == "extract" else "repair_synthesis"
