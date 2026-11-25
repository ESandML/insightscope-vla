"""Small helpers so every rule builds discrepancies the same way."""

from __future__ import annotations

from insightscope.domain.models import (
    Assertion,
    Discrepancy,
    DiscrepancyKind,
    Severity,
    TimeSpan,
    make_discrepancy_id,
)
from insightscope.domain.ontology import Attribute


def claim_discrepancy(
    rule_id: str,
    kind: DiscrepancyKind,
    severity: Severity,
    claim: Assertion,
    *,
    observation: Assertion | None = None,
    det_confidence: float = 0.8,
    note: str = "",
) -> Discrepancy:
    return Discrepancy(
        discrepancy_id=make_discrepancy_id(
            rule_id,
            claim.subject_id,
            claim.attribute,
            claim.span,
            observation.span if observation is not None else None,
        ),
        rule_id=rule_id,
        kind=kind,
        severity=severity,
        subject_id=claim.subject_id,
        attribute=claim.attribute,
        span_seen=observation.span if observation is not None else None,
        span_said=claim.span,
        evidence_refs=observation.evidence_refs if observation is not None else claim.evidence_refs,
        det_confidence=det_confidence,
        note=note,
    )


def subject_discrepancy(
    rule_id: str,
    kind: DiscrepancyKind,
    severity: Severity,
    subject_id: str,
    *,
    attribute: Attribute | None = None,
    span_seen: TimeSpan | None = None,
    span_said: TimeSpan | None = None,
    evidence_refs: tuple[str, ...] = (),
    det_confidence: float = 0.5,
    note: str = "",
) -> Discrepancy:
    return Discrepancy(
        discrepancy_id=make_discrepancy_id(
            rule_id,
            subject_id,
            attribute,
            span_said,
            span_seen,
        ),
        rule_id=rule_id,
        kind=kind,
        severity=severity,
        subject_id=subject_id,
        attribute=attribute,
        span_seen=span_seen,
        span_said=span_said,
        evidence_refs=evidence_refs,
        det_confidence=det_confidence,
        note=note,
    )
