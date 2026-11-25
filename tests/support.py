"""Builders shared by the reconciliation tests.

Plain functions rather than fixtures: a test that says
``claim("laptop", Attribute.OPEN_CLOSED, "closed", start=12)`` is readable on its own,
and the defaults keep boilerplate out of the interesting part.
"""

from __future__ import annotations

from insightscope.domain.models import (
    Assertion,
    ChangeEvent,
    EvidenceManifest,
    InteractionProposal,
    KeyframeRef,
    Provenance,
    TimeSpan,
    make_assertion_id,
)
from insightscope.domain.ontology import Attribute, AttributeValue


def make_span(start: float, duration: float = 1.0) -> TimeSpan:
    return TimeSpan(t_start_s=start, t_end_s=start + duration)


def assertion(
    *,
    subject: str,
    attribute: Attribute,
    value: AttributeValue,
    start: float = 10.0,
    duration: float = 1.0,
    modality: str = "acoustic",
    confidence: float = 0.8,
    evidence: tuple[str, ...] = ("kf_0001",),
) -> Assertion:
    span = make_span(start, duration)
    return Assertion(
        assertion_id=make_assertion_id(modality, subject, attribute, value, span),  # type: ignore[arg-type]
        modality=modality,  # type: ignore[arg-type]
        subject_id=subject,
        attribute=attribute,
        value=value,
        span=span,
        evidence_refs=evidence,
        confidence=confidence,
        provenance=Provenance(model="fake", prompt_version="test"),
    )


def claim(
    subject: str,
    attribute: Attribute,
    value: AttributeValue,
    *,
    start: float = 10.0,
    duration: float = 1.0,
) -> Assertion:
    return assertion(
        subject=subject,
        attribute=attribute,
        value=value,
        start=start,
        duration=duration,
        modality="acoustic",
    )


def observation(
    subject: str,
    attribute: Attribute,
    value: AttributeValue,
    *,
    start: float = 10.0,
    duration: float = 1.0,
    confidence: float = 0.9,
    evidence: tuple[str, ...] = ("kf_0001",),
) -> Assertion:
    return assertion(
        subject=subject,
        attribute=attribute,
        value=value,
        start=start,
        duration=duration,
        modality="vision",
        confidence=confidence,
        evidence=evidence,
    )


def keyframe(
    keyframe_id: str = "kf_0001",
    *,
    start: float = 0.0,
    end: float = 60.0,
) -> KeyframeRef:
    return KeyframeRef(
        keyframe_id=keyframe_id,
        uri=f"artifacts/run/keyframes/{keyframe_id}.jpg",
        sha256=f"sha-{keyframe_id}",
        span=TimeSpan(t_start_s=start, t_end_s=end),
        reason="anchor",
        width=640,
        height=360,
    )


def manifest(*, start: float = 0.0, end: float = 60.0) -> EvidenceManifest:
    """One anchor keyframe covering the whole window: everything is observed."""
    return EvidenceManifest(
        bundle_id="b1",
        source_path="clip.mp4",
        duration_s=end,
        keyframes=(keyframe("kf_0001", start=start, end=end),),
    )


def empty_manifest() -> EvidenceManifest:
    return EvidenceManifest(bundle_id="b1", source_path="clip.mp4", duration_s=60.0)


def change_event(
    subject: str,
    *,
    start: float = 10.0,
    keyframe_id: str = "kf_0002",
    description: str = "",
) -> ChangeEvent:
    return ChangeEvent(
        keyframe_id=keyframe_id,
        span=make_span(start),
        subject_id=subject,
        description=description,
        confidence=0.8,
    )


def proposal(
    object_hint: str,
    *,
    start: float = 10.0,
    keyframe_id: str = "kf_0002",
) -> InteractionProposal:
    return InteractionProposal(
        keyframe_id=keyframe_id,
        span=make_span(start),
        object_hint=object_hint,
    )
