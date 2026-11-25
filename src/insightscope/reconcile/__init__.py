"""Deterministic reconciliation: the part of the system that decides.

No model is called anywhere in this package, and the import-linter contract in CI
enforces that. If a change here needs a model to work, it belongs in ``clients/``.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from insightscope.config import RunConfig
from insightscope.domain.aliases import AliasTable
from insightscope.domain.models import (
    Alignment,
    Assertion,
    ChangeEvent,
    Discrepancy,
    EvidenceManifest,
    Finding,
    InteractionProposal,
    ReconcileStats,
    ResolutionRecord,
)
from insightscope.domain.registry import SubjectRegistry
from insightscope.reconcile.adjudicate import adjudicate
from insightscope.reconcile.align import align_claims
from insightscope.reconcile.context import build_context
from insightscope.reconcile.resolution import resolve_claims
from insightscope.reconcile.rules import run_rules


class ReconcileResult(BaseModel):
    """Everything the reconciler produced, ready to be dropped into graph state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claims: tuple[Assertion, ...] = ()
    resolutions: tuple[ResolutionRecord, ...] = ()
    alignments: tuple[Alignment, ...] = ()
    discrepancies: tuple[Discrepancy, ...] = ()
    findings: tuple[Finding, ...] = ()
    stats: ReconcileStats = Field(default_factory=ReconcileStats)


def reconcile(
    *,
    claims: Sequence[Assertion],
    observations: Sequence[Assertion],
    evidence: EvidenceManifest,
    config: RunConfig,
    proposals: Sequence[InteractionProposal] = (),
    changes: Sequence[ChangeEvent] = (),
    requested_subjects: Sequence[str] | None = None,
) -> ReconcileResult:
    """Resolve, align, apply rules, and adjudicate.

    ``requested_subjects`` is the list the vision step was asked about. When it is
    omitted the "camera saw something nobody asked for" check is skipped, because
    there is nothing to compare against.
    """
    aliases = config.checklist.alias_table() if config.checklist is not None else AliasTable.empty()

    resolution = resolve_claims(
        claims=claims,
        proposals=proposals,
        aliases=aliases,
        tolerance_s=config.alignment.tolerance_s,
    )
    bound_claims = resolution.claims

    alignments = align_claims(
        claims=bound_claims,
        observations=observations,
        window=config.alignment.window(),
    )

    registry = SubjectRegistry.build(
        said=bound_claims,
        seen=observations,
        checklist=config.checklist,
    )

    context = build_context(
        claims=bound_claims,
        observations=observations,
        changes=changes,
        alignments=alignments,
        evidence=evidence,
        registry=registry,
        config=config,
        requested_subjects=requested_subjects,
    )

    discrepancies = run_rules(context)
    findings, stats = adjudicate(
        discrepancies,
        n_claims=len(bound_claims),
        n_observations=len(observations),
    )

    return ReconcileResult(
        claims=tuple(bound_claims),
        resolutions=resolution.records,
        alignments=alignments,
        discrepancies=tuple(discrepancies),
        findings=tuple(findings),
        stats=stats,
    )
