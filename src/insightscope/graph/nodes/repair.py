"""Repair bookkeeping.

These nodes do not talk to a model and do not decide anything: the router already
decided. They bump the cycle, carry the critic's issues into the next attempt, and
leave a trace so tests can prove the loop actually ran.
"""

from __future__ import annotations

from insightscope.contracts.report import Issue
from insightscope.graph.nodes._common import NodeUpdate, attempt, cycle_of
from insightscope.graph.policy import actionable
from insightscope.graph.state import AuditState


def _issues_from_critique(state: AuditState) -> list[Issue]:
    critique = state.get("critique")
    if critique is None:
        return []
    return actionable(critique.issues)


def repair_synthesis(state: AuditState) -> NodeUpdate:
    cycle = cycle_of(state) + 1
    return {
        "cycle": cycle,
        "repair_target": "synthesize",
        "pending_issues": _issues_from_critique(state),
        "attempts": [attempt("repair_synthesis", cycle)],
        "trace": ["repair_synthesis"],
    }


def repair_extraction(state: AuditState) -> NodeUpdate:
    cycle = cycle_of(state) + 1
    return {
        "cycle": cycle,
        "repair_target": "extract",
        "pending_issues": _issues_from_critique(state),
        "attempts": [attempt("repair_extraction", cycle)],
        "trace": ["repair_extraction"],
    }
