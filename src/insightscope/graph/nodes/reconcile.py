"""Reconciliation node: calls the deterministic layer and stores one bundle."""

from __future__ import annotations

from insightscope.graph.nodes._common import NodeUpdate
from insightscope.graph.state import AuditState
from insightscope.reconcile import reconcile


def reconcile_node(state: AuditState) -> NodeUpdate:
    result = reconcile(
        claims=state.get("claims") or [],
        observations=state.get("observations") or [],
        proposals=state.get("proposals") or [],
        changes=state.get("changes") or [],
        evidence=state["evidence"],
        config=state["config"],
        requested_subjects=state.get("requested_subjects"),
    )
    return {
        "reconciliation": result,
        "trace": ["reconcile"],
        "status": "synthesizing",
    }
