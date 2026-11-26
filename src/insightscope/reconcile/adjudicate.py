"""Turning raw rule hits into an ordered, deduplicated list of findings.

Two rules can notice the same disagreement from different angles, and one rule can
fire on several overlapping keyframes. Adjudication collapses those into one finding
so the report does not repeat itself, decides how confident we are allowed to be, and
sorts by severity so the important things are at the top.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from insightscope.domain.models import (
    SEVERITY_RANK,
    Discrepancy,
    Finding,
    FindingStatus,
    ReconcileStats,
    TimeSpan,
    make_finding_id,
)

# Below this the finding stays in the report but is labelled as not established.
CONFIRMED_THRESHOLD = 0.5


def adjudicate(
    discrepancies: Sequence[Discrepancy],
    *,
    n_claims: int = 0,
    n_observations: int = 0,
) -> tuple[list[Finding], ReconcileStats]:
    """Deduplicate, assign status, sort, and summarise."""
    best: dict[tuple[object, ...], Discrepancy] = {}
    for discrepancy in discrepancies:
        key = _dedupe_key(discrepancy)
        current = best.get(key)
        if current is None or discrepancy.det_confidence > current.det_confidence:
            best[key] = discrepancy

    findings = [_to_finding(discrepancy) for discrepancy in best.values()]
    findings.sort(key=_sort_key)

    stats = ReconcileStats(
        n_claims=n_claims,
        n_observations=n_observations,
        n_discrepancies=len(discrepancies),
        counts_by_rule=dict(sorted(Counter(f.discrepancy.rule_id for f in findings).items())),
        counts_by_severity=_severity_counts(findings),
    )
    return findings, stats


def _dedupe_key(discrepancy: Discrepancy) -> tuple[object, ...]:
    return (
        discrepancy.rule_id,
        discrepancy.subject_id,
        discrepancy.attribute,
        discrepancy.action,
        _span_key(discrepancy.span_said),
        _span_key(discrepancy.span_seen),
    )


def _span_key(span: TimeSpan | None) -> tuple[float, float] | None:
    return None if span is None else (span.t_start_s, span.t_end_s)


def _status(discrepancy: Discrepancy) -> FindingStatus:
    if discrepancy.kind == "insufficient_evidence":
        return "insufficient_evidence"
    if SEVERITY_RANK[discrepancy.severity] <= SEVERITY_RANK["minor"]:
        return "open"
    if discrepancy.det_confidence < CONFIRMED_THRESHOLD:
        return "open"
    return "confirmed"


def _to_finding(discrepancy: Discrepancy) -> Finding:
    return Finding(
        finding_id=make_finding_id(discrepancy.discrepancy_id),
        discrepancy=discrepancy,
        status=_status(discrepancy),
        rationale=discrepancy.note,
    )


def _sort_key(finding: Finding) -> tuple[object, ...]:
    discrepancy = finding.discrepancy
    starts = [
        span.t_start_s
        for span in (discrepancy.span_said, discrepancy.span_seen)
        if span is not None
    ]
    return (
        -SEVERITY_RANK[discrepancy.severity],
        min(starts) if starts else 0.0,
        discrepancy.subject_id,
        discrepancy.rule_id,
        discrepancy.discrepancy_id,
    )


def _severity_counts(findings: Sequence[Finding]) -> dict[str, int]:
    counts = Counter(finding.severity for finding in findings)
    ordered: dict[str, int] = {}
    for severity in ("blocker", "major", "minor", "info"):
        value = counts.get(severity)
        if value:
            ordered[severity] = value
    return ordered


__all__ = ["CONFIRMED_THRESHOLD", "adjudicate"]
