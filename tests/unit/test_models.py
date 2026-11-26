"""Time spans, evidence coverage, assertions, and content-addressed ids."""

import pytest
from pydantic import ValidationError

from insightscope.domain.models import (
    Assertion,
    EvidenceManifest,
    KeyframeRef,
    Provenance,
    TimeSpan,
    make_assertion_id,
    make_discrepancy_id,
    merge_spans,
)
from insightscope.domain.ontology import Attribute


def span(start: float, end: float) -> TimeSpan:
    return TimeSpan(t_start_s=start, t_end_s=end)


def make_assertion(
    subject: str = "laptop",
    attribute: Attribute = Attribute.OPEN_CLOSED,
    value: object = "closed",
    start: float = 0.0,
    modality: str = "acoustic",
) -> Assertion:
    time_span = span(start, start + 1.0)
    return Assertion(
        assertion_id=make_assertion_id(modality, subject, attribute, value, time_span),  # type: ignore[arg-type]
        modality=modality,  # type: ignore[arg-type]
        subject_id=subject,
        attribute=attribute,
        value=value,  # type: ignore[arg-type]
        span=time_span,
        provenance=Provenance(model="fake"),
    )


def test_span_rejects_reversed_times() -> None:
    with pytest.raises(ValidationError):
        TimeSpan(t_start_s=5.0, t_end_s=1.0)


def test_gap_and_overlap() -> None:
    assert span(0, 1).gap_s(span(3, 4)) == 2.0
    assert span(0, 2).gap_s(span(1, 3)) == 0.0
    assert span(0, 2).overlaps(span(2.5, 3), tolerance_s=1.0)
    assert not span(0, 2).overlaps(span(2.5, 3), tolerance_s=0.25)


def test_merge_spans_coalesces_and_sorts() -> None:
    merged = merge_spans([span(5, 6), span(0, 2), span(1.5, 3)])
    assert [(m.t_start_s, m.t_end_s) for m in merged] == [(0, 3), (5, 6)]


def test_assertion_coerces_values() -> None:
    assertion = make_assertion(attribute=Attribute.COUNT, value="2")
    assert assertion.value == 2
    assert isinstance(assertion.value, int)


def test_assertion_ids_are_deterministic() -> None:
    first = make_assertion()
    second = make_assertion()
    assert first.assertion_id == second.assertion_id

    different = make_assertion(value="open")
    assert different.assertion_id != first.assertion_id


def action_assertion(action: str, value: bool = True) -> Assertion:
    span = TimeSpan(t_start_s=10.0, t_end_s=11.0)
    return Assertion(
        assertion_id=make_assertion_id(
            "acoustic", "kettle", Attribute.ACTION_COMPLETED, value, span, action
        ),
        modality="acoustic",
        subject_id="kettle",
        attribute=Attribute.ACTION_COMPLETED,
        action=action,
        value=value,
        span=span,
        provenance=Provenance(model="fake"),
    )


def test_action_is_required_for_action_completed() -> None:
    with pytest.raises(ValidationError, match="action is required"):
        Assertion(
            assertion_id="a" * 12,
            modality="acoustic",
            subject_id="kettle",
            attribute=Attribute.ACTION_COMPLETED,
            value=True,
            span=span(0, 1),
            provenance=Provenance(model="fake"),
        )


def test_action_is_rejected_for_other_attributes() -> None:
    with pytest.raises(ValidationError, match="only valid for action_completed"):
        Assertion(
            assertion_id="a" * 12,
            modality="acoustic",
            subject_id="kettle",
            attribute=Attribute.PRESENCE,
            action="fill",
            value=True,
            span=span(0, 1),
            provenance=Provenance(model="fake"),
        )


def test_action_is_normalised() -> None:
    assertion = action_assertion("Wipe Counter")
    assert assertion.action == "wipe_counter"


def test_same_subject_different_actions_do_not_collide() -> None:
    fill = action_assertion("fill")
    pour = action_assertion("pour")
    assert fill.assertion_id != pour.assertion_id

    time_span = TimeSpan(t_start_s=10.0, t_end_s=11.0)
    fill_id = make_discrepancy_id(
        "R-ACT-001", "kettle", Attribute.ACTION_COMPLETED, time_span, None, "fill"
    )
    pour_id = make_discrepancy_id(
        "R-ACT-001", "kettle", Attribute.ACTION_COMPLETED, time_span, None, "pour"
    )
    assert fill_id != pour_id


def test_subject_kind_follows_attribute() -> None:
    assert make_assertion(attribute=Attribute.STEP_COMPLETED, value=True).subject_kind == "step"
    assert make_assertion().subject_kind == "object"


def manifest(keyframes: list[KeyframeRef]) -> EvidenceManifest:
    return EvidenceManifest(
        bundle_id="b1",
        source_path="clip.mp4",
        duration_s=30.0,
        keyframes=tuple(keyframes),
    )


def keyframe(index: int, start: float, end: float) -> KeyframeRef:
    return KeyframeRef(
        keyframe_id=f"kf_{index:04d}",
        uri=f"artifacts/run/keyframes/kf_{index:04d}.jpg",
        sha256=f"{index:08d}",
        span=span(start, end),
        reason="motion",
        width=640,
        height=360,
    )


def test_coverage_is_the_union_of_keyframe_spans() -> None:
    evidence = manifest([keyframe(1, 0, 1), keyframe(2, 0.5, 2), keyframe(3, 10, 11)])
    assert [(c.t_start_s, c.t_end_s) for c in evidence.coverage] == [(0, 2), (10, 11)]


def test_absence_requires_uncovered_time() -> None:
    evidence = manifest([keyframe(1, 10, 11)])
    # A claim at 30s has no keyframe anywhere near it: "insufficient", not "false".
    assert not evidence.has_evidence_within(span(30, 31), tolerance_s=3.0)
    assert evidence.has_evidence_within(span(10.5, 11.5), tolerance_s=3.0)


def test_empty_evidence_covers_nothing() -> None:
    assert manifest([]).coverage == []
    assert not manifest([]).has_evidence_within(span(0, 1), tolerance_s=10.0)
