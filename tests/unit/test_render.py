"""Report rendering: one table for open-ended runs, two for spec runs."""

from tests.support import manifest

from insightscope.domain.models import (
    Discrepancy,
    Finding,
    TimeSpan,
    make_discrepancy_id,
    make_finding_id,
)
from insightscope.domain.ontology import Attribute
from insightscope.report.render import is_process_finding, render_markdown


def finding(
    rule_id: str,
    *,
    severity: str = "major",
    subject: str = "kettle",
    start: float = 10.0,
) -> Finding:
    span = TimeSpan(t_start_s=start, t_end_s=start + 1.0)
    step = rule_id.startswith("R-STEP-")
    attribute = Attribute.STEP_COMPLETED if step else Attribute.OPEN_CLOSED
    discrepancy = Discrepancy(
        discrepancy_id=make_discrepancy_id(rule_id, subject, attribute, span, None),
        rule_id=rule_id,
        kind="sequence_violation" if step else "contradiction",
        severity=severity,  # type: ignore[arg-type]
        subject_id=subject,
        attribute=attribute,
        span_said=span,
        det_confidence=0.9,
    )
    return Finding(
        finding_id=make_finding_id(discrepancy.discrepancy_id),
        discrepancy=discrepancy,
        status="confirmed",
    )


def render(findings: list[Finding], *, has_spec: bool) -> str:
    return render_markdown(
        run_id="run-test",
        evidence=manifest(),
        findings=findings,
        narrative="summary",
        status="complete",
        has_spec=has_spec,
    )


def test_open_ended_run_keeps_one_table() -> None:
    report = render([finding("R-STATE-001")], has_spec=False)

    assert "## Findings (1)" in report
    assert "### Process / Spec Compliance" not in report
    assert "### Speech / Transcript Verification" not in report
    assert report.count("| Severity |") == 1


def test_spec_run_splits_into_two_sections() -> None:
    report = render(
        [finding("R-STEP-003"), finding("R-STATE-001")],
        has_spec=True,
    )

    assert report.index("### Process / Spec Compliance") < report.index(
        "### Speech / Transcript Verification"
    )
    assert "R-STEP-003" in report
    assert "R-STATE-001" in report
    assert report.count("| Severity |") == 2


def test_spec_run_with_no_process_findings_says_so() -> None:
    report = render([finding("R-STATE-001")], has_spec=True)

    assert "### Process / Spec Compliance" in report
    assert "No deviations from the spec." in report
    assert "R-STATE-001" in report


def test_spec_run_with_no_speech_findings_says_so() -> None:
    report = render([finding("R-STEP-003")], has_spec=True)

    assert "### Speech / Transcript Verification" in report
    assert "No speech or observation conflicts." in report
    assert "R-STEP-003" in report


def test_both_families_split_even_without_a_spec_flag() -> None:
    report = render([finding("R-STEP-002"), finding("R-PRES-001")], has_spec=False)
    assert "### Process / Spec Compliance" in report
    assert report.count("| Severity |") == 2


def test_process_findings_are_identified_by_rule_family() -> None:
    assert is_process_finding(finding("R-STEP-001"))
    assert not is_process_finding(finding("R-COVER-002"))
