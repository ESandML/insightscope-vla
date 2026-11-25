"""The one object that flows between graph nodes.

Rules of this state:

* No image bytes, ever. Only references, spans, and hashes.
* Anything a fan-out writes is an append-only ledger (``attempts``, ``errors``,
  ``trace``, ``critique_history``), so parallel writes cannot clobber each other.
* Everything routing needs is a plain value here. Routers are pure functions of this
  dict, which is why they can be tested without compiling a graph or calling a model.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from insightscope.config import RunConfig
from insightscope.contracts.report import Critique, Issue, ReportDraft
from insightscope.domain.models import (
    ActionsSummary,
    Assertion,
    AuditReport,
    ChangeEvent,
    EvidenceManifest,
    InteractionProposal,
)
from insightscope.reconcile import ReconcileResult

RunStatus = Literal[
    "new",
    "extracting",
    "synthesizing",
    "validating",
    "critiquing",
    "complete",
    "complete_with_caveats",
    "escalated",
    "failed",
]

NodeName = Literal[
    "ingest",
    "extract_claims",
    "extract_observations",
    "reconcile",
    "synthesize",
    "validate",
    "critique",
    "repair_synthesis",
    "repair_extraction",
    "finalize",
    "finalize_caveats",
    "escalate",
    "dispatch_actions",
]

RepairTarget = Literal["extract", "synthesize", "none"]


class Attempt(BaseModel):
    """One execution of one node. Budgets are counted from this ledger."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node: NodeName
    cycle: int = 0
    verdict: Literal["ok", "accept", "revise", "error"] = "ok"
    latency_ms: int = 0
    error_code: str | None = None


class NodeError(BaseModel):
    """Something a node refused to accept. Never fatal by itself; routing decides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node: NodeName
    code: str
    message: str


class ValidationProblem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Literal[
        "empty_draft",
        "unknown_citation",
        "missing_citation",
        "no_findings_cited",
    ]
    ref: str = ""
    message: str = ""


class ValidationResult(BaseModel):
    """Deterministic gate output. Runs before the critic to save tokens."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    problems: tuple[ValidationProblem, ...] = Field(default_factory=tuple)


class AuditState(TypedDict, total=False):
    # Identity and inputs, set before the first node runs.
    run_id: str
    config: RunConfig
    evidence: EvidenceManifest

    # Extraction.
    claims: list[Assertion]
    observations: list[Assertion]
    proposals: list[InteractionProposal]
    changes: list[ChangeEvent]
    requested_subjects: list[str]

    # Deterministic reconciliation (one bundle keeps the state small).
    reconciliation: ReconcileResult

    # Synthesis and verification.
    draft: ReportDraft | None
    validation: ValidationResult | None
    critique: Critique | None
    critique_history: Annotated[list[Critique], operator.add]

    # Control plane.
    pending_issues: list[Issue]
    repair_target: RepairTarget
    cycle: int
    attempts: Annotated[list[Attempt], operator.add]
    status: RunStatus
    fatal: str | None

    # Outputs.
    actions: ActionsSummary | None
    report: AuditReport | None
    errors: Annotated[list[NodeError], operator.add]
    trace: Annotated[list[str], operator.add]
