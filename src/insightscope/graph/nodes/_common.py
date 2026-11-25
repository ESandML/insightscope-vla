"""Small shared helpers for nodes: aliasing, attempt records, failure updates."""

from __future__ import annotations

from typing import Any

from insightscope.clients.base import ClientError
from insightscope.config import RunConfig
from insightscope.domain.aliases import AliasTable
from insightscope.graph.state import Attempt, AuditState, NodeError, NodeName

NodeUpdate = dict[str, Any]


def alias_table(config: RunConfig) -> AliasTable:
    return config.checklist.alias_table() if config.checklist is not None else AliasTable.empty()


def attempt(
    node: NodeName,
    cycle: int,
    *,
    verdict: str = "ok",
    error_code: str | None = None,
) -> Attempt:
    return Attempt(node=node, cycle=cycle, verdict=verdict, error_code=error_code)  # type: ignore[arg-type]


def failed(node: NodeName, exc: ClientError, cycle: int) -> NodeUpdate:
    """A model call failed. Record it, mark the run fatal, and let routing decide."""
    return {
        "fatal": f"{node}: {exc}",
        "errors": [NodeError(node=node, code=exc.code, message=str(exc))],
        "attempts": [attempt(node, cycle, verdict="error", error_code=exc.code)],
        "status": "failed",
        "trace": [node],
    }


def cycle_of(state: AuditState) -> int:
    return state.get("cycle", 0)
