"""Assemble the graph.

The wiring is deliberately boring: every conditional edge points at a function in
``policy.py``, and every node has exactly one job. If you want to know what the system
does, read this file, then read ``policy.py``.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from insightscope.clients.base import TextClient, VisionClient
from insightscope.graph.nodes.dispatch import dispatch_actions
from insightscope.graph.nodes.extract import make_extract_claims, make_extract_observations
from insightscope.graph.nodes.finalize import escalate, finalize, finalize_caveats
from insightscope.graph.nodes.ingest import ingest
from insightscope.graph.nodes.reconcile import reconcile_node
from insightscope.graph.nodes.repair import repair_extraction, repair_synthesis
from insightscope.graph.nodes.verify import make_critique, make_synthesize, validate
from insightscope.graph.policy import route_after_critique, route_after_validate
from insightscope.graph.state import AuditState


def build_graph(
    *,
    text_client: TextClient,
    vision_client: VisionClient,
    checkpointer: Any | None = None,
) -> Any:
    """Compile the audit graph. Clients are injected, never stored in state.

    ``Any`` is confined to this function: LangGraph's generic ``StateGraph`` infers
    ``Never`` for the state type under mypy strict, and fighting that here would add
    casts to every node without buying any safety. Node signatures are typed.
    """
    builder: Any = StateGraph(AuditState)

    builder.add_node("ingest", ingest)
    builder.add_node("extract_claims", make_extract_claims(text_client))
    builder.add_node("extract_observations", make_extract_observations(vision_client))
    builder.add_node("reconcile", reconcile_node)
    builder.add_node("synthesize", make_synthesize(text_client))
    builder.add_node("validate", validate)
    builder.add_node("critique", make_critique(text_client))
    builder.add_node("repair_synthesis", repair_synthesis)
    builder.add_node("repair_extraction", repair_extraction)
    builder.add_node("finalize", finalize)
    builder.add_node("finalize_caveats", finalize_caveats)
    builder.add_node("escalate", escalate)
    builder.add_node("dispatch_actions", dispatch_actions)

    builder.add_edge(START, "ingest")
    builder.add_edge("ingest", "extract_claims")
    builder.add_edge("extract_claims", "extract_observations")
    builder.add_edge("extract_observations", "reconcile")
    builder.add_edge("reconcile", "synthesize")
    builder.add_edge("synthesize", "validate")

    builder.add_conditional_edges("validate", route_after_validate)
    builder.add_conditional_edges("critique", route_after_critique)

    builder.add_edge("repair_synthesis", "synthesize")
    builder.add_edge("repair_extraction", "extract_claims")

    builder.add_edge("finalize", "dispatch_actions")
    builder.add_edge("finalize_caveats", "dispatch_actions")
    builder.add_edge("escalate", "dispatch_actions")
    builder.add_edge("dispatch_actions", END)

    return builder.compile(checkpointer=checkpointer)
