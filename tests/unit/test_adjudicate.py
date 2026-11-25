"""Deduplication, status assignment, ordering, and summary counts."""

from insightscope.domain.models import Discrepancy, TimeSpan, make_discrepancy_id
from insightscope.domain.ontology import Attribute
from insightscope.reconcile.adjudicate import adjudicate


def discrepancy(
    *,
    rule_id: str = "R-PRES-001",
    kind: str = "contradiction",
    severity: str = "major",
    subject: str = "laptop",
    start: float = 10.0,
    det: float = 0.9,
) -> Discrepancy:
    said = TimeSpan(t_start_s=start, t_end_s=start + 1.0)
    return Discrepancy(
        discrepancy_id=make_discrepancy_id(rule_id, subject, Attribute.PRESENCE, said, None),
        rule_id=rule_id,
        kind=kind,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        subject_id=subject,
        attribute=Attribute.PRESENCE,
        span_said=said,
        det_confidence=det,
    )


def test_duplicates_collapse_to_the_most_confident_hit() -> None:
    findings, stats = adjudicate([discrepancy(det=0.6), discrepancy(det=0.9)])
    assert len(findings) == 1
    assert findings[0].discrepancy.det_confidence == 0.9
    assert stats.n_discrepancies == 2


def test_same_rule_at_different_times_is_not_a_duplicate() -> None:
    findings, _ = adjudicate([discrepancy(start=10.0), discrepancy(start=20.0)])
    assert len(findings) == 2


def test_status_mapping() -> None:
    findings, _ = adjudicate(
        [
            discrepancy(rule_id="R-PRES-001", kind="contradiction", severity="major"),
            discrepancy(rule_id="R-LOC-001", kind="value_mismatch", severity="minor"),
            discrepancy(rule_id="R-COVER-001", kind="insufficient_evidence", severity="info"),
            discrepancy(rule_id="R-OMIT-001", kind="omission", severity="info", subject="chair"),
            discrepancy(rule_id="R-PRES-002", kind="contradiction", severity="major", det=0.3),
        ]
    )
    by_rule = {finding.discrepancy.rule_id: finding.status for finding in findings}
    assert by_rule["R-PRES-001"] == "confirmed"
    assert by_rule["R-LOC-001"] == "open"
    assert by_rule["R-COVER-001"] == "insufficient_evidence"
    assert by_rule["R-OMIT-001"] == "open"
    assert by_rule["R-PRES-002"] == "open"  # low rule confidence: reported, not confirmed


def test_findings_are_sorted_by_severity_then_time() -> None:
    findings, _ = adjudicate(
        [
            discrepancy(rule_id="R-COVER-001", kind="insufficient_evidence", severity="info"),
            discrepancy(rule_id="R-LOC-001", kind="value_mismatch", severity="minor", start=5.0),
            discrepancy(rule_id="R-STATE-001", kind="contradiction", severity="major", start=30.0),
            discrepancy(rule_id="R-PRES-001", kind="contradiction", severity="major", start=10.0),
        ]
    )
    assert [f.discrepancy.rule_id for f in findings] == [
        "R-PRES-001",
        "R-STATE-001",
        "R-LOC-001",
        "R-COVER-001",
    ]


def test_stats_count_findings_after_deduplication() -> None:
    _, stats = adjudicate(
        [discrepancy(det=0.6), discrepancy(det=0.9), discrepancy(subject="mug", start=20.0)],
        n_claims=4,
        n_observations=5,
    )
    assert stats.n_claims == 4
    assert stats.n_observations == 5
    assert stats.n_discrepancies == 3
    assert stats.counts_by_rule == {"R-PRES-001": 2}
    assert stats.counts_by_severity == {"major": 2}
