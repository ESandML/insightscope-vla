"""The nouns of an audit: time spans, evidence, assertions, findings.

Everything here is a plain Pydantic model so it can be validated, serialised to the
checkpoint, and compared in tests. Ids are content hashes rather than random uuids:
the same input produces the same id, which makes reruns idempotent and lets the
action layer write files and database rows without worrying about duplicates.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from insightscope.domain.ontology import Attribute, AttributeValue, coerce_value

Severity = Literal["blocker", "major", "minor", "info"]
DiscrepancyKind = Literal[
    "contradiction",
    "value_mismatch",
    "omission",
    "unsupported",
    "temporal_mismatch",
    "sequence_violation",
    "missing_step",
    "unresolved_reference",
    "subject_unmatched",
    "insufficient_evidence",
]
KeyframeReason = Literal["motion", "snap_before", "snap_after", "anchor", "fallback"]
TranscriptionMode = Literal["json", "text", "asr", "none"]
Modality = Literal["vision", "acoustic"]
FindingStatus = Literal["open", "confirmed", "dismissed", "insufficient_evidence"]

SEVERITY_RANK: dict[Severity, int] = {"info": 0, "minor": 1, "major": 2, "blocker": 3}


def _hash(*parts: object) -> str:
    payload = "|".join(str(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


class TimeSpan(BaseModel):
    """Seconds from the start of the recording. Never wall-clock, never frame counts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    t_start_s: float = Field(ge=0.0)
    t_end_s: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _ordered(self) -> TimeSpan:
        if self.t_end_s < self.t_start_s:
            raise ValueError(f"t_end_s ({self.t_end_s}) is before t_start_s ({self.t_start_s})")
        return self

    @property
    def duration_s(self) -> float:
        return self.t_end_s - self.t_start_s

    @property
    def mid_s(self) -> float:
        return (self.t_start_s + self.t_end_s) / 2.0

    def gap_s(self, other: TimeSpan) -> float:
        """Seconds between the two spans; 0.0 when they touch or overlap."""
        if self.t_end_s < other.t_start_s:
            return other.t_start_s - self.t_end_s
        if other.t_end_s < self.t_start_s:
            return self.t_start_s - other.t_end_s
        return 0.0

    def overlaps(self, other: TimeSpan, tolerance_s: float = 0.0) -> bool:
        return self.gap_s(other) <= tolerance_s

    def expand(self, tolerance_s: float) -> TimeSpan:
        return TimeSpan(
            t_start_s=max(0.0, self.t_start_s - tolerance_s),
            t_end_s=self.t_end_s + tolerance_s,
        )

    def contains(self, seconds: float) -> bool:
        return self.t_start_s <= seconds <= self.t_end_s


def merge_spans(spans: Iterable[TimeSpan]) -> list[TimeSpan]:
    """Union of spans, sorted and coalesced. Used to answer 'was this window observed?'."""
    merged: list[TimeSpan] = []
    for span in sorted(spans, key=lambda s: (s.t_start_s, s.t_end_s)):
        if merged and span.t_start_s <= merged[-1].t_end_s:
            last = merged[-1]
            if span.t_end_s > last.t_end_s:
                merged[-1] = TimeSpan(t_start_s=last.t_start_s, t_end_s=span.t_end_s)
        else:
            merged.append(span)
    return merged


class KeyframeRef(BaseModel):
    """A picture we are allowed to look at. The bytes live on disk, not in state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    keyframe_id: str = Field(min_length=4)
    uri: str = Field(min_length=1)
    sha256: str = Field(min_length=8)
    span: TimeSpan
    reason: KeyframeReason
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class Utterance(BaseModel):
    """One stretch of speech, from a transcript file or speech-to-text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    utterance_id: str = Field(min_length=4)
    text: str = Field(min_length=1)
    span: TimeSpan
    speaker: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class EvidenceManifest(BaseModel):
    """What the run actually observed, and how well it is covered in time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bundle_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    duration_s: float = Field(ge=0.0)
    keyframes: tuple[KeyframeRef, ...] = ()
    utterances: tuple[Utterance, ...] = ()
    transcript_mode: TranscriptionMode = "none"
    notes: tuple[str, ...] = ()

    @property
    def coverage(self) -> list[TimeSpan]:
        """Time spans that at least one keyframe observed."""
        return merge_spans(k.span for k in self.keyframes)

    def has_evidence_within(self, span: TimeSpan, tolerance_s: float) -> bool:
        """True when some keyframe observed the neighbourhood of ``span``.

        Rules use this before claiming something was *not* seen. Sparse sampling is
        not proof of absence, and the difference is the difference between an audit
        and an accusation.
        """
        window = span.expand(tolerance_s)
        return any(covered.overlaps(window) for covered in self.coverage)


class Provenance(BaseModel):
    """Which model said this, from which prompt. Needed to explain a finding later."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(min_length=1)
    prompt_version: str = "v0"


class Assertion(BaseModel):
    """One thing a model claims to have seen or heard, in a comparable shape."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assertion_id: str = Field(min_length=6)
    modality: Modality
    subject_id: str = Field(min_length=1)
    attribute: Attribute
    value: AttributeValue
    span: TimeSpan
    evidence_refs: tuple[str, ...] = ()
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    provenance: Provenance

    @field_validator("value")
    @classmethod
    def _canonical_value(cls, value: object, info: ValidationInfo) -> AttributeValue:
        # ``attribute`` is declared before ``value``, so it is already validated here.
        attribute = info.data.get("attribute")
        if not isinstance(attribute, Attribute):
            raise ValueError("attribute must be validated before value")
        return coerce_value(attribute, value)

    @property
    def subject_kind(self) -> Literal["object", "step"]:
        return self.attribute.subject_kind


def make_assertion_id(
    modality: Modality,
    subject_id: str,
    attribute: Attribute,
    value: AttributeValue,
    span: TimeSpan,
) -> str:
    return _hash(
        modality,
        subject_id,
        attribute.value,
        repr(value),
        f"{span.t_start_s:.3f}",
        f"{span.t_end_s:.3f}",
    )


class Alignment(BaseModel):
    """A said/seen pair the aligner considered, and how close in time it was."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=6)
    observation_id: str | None = None
    delta_s: float | None = None
    matched: bool = False


class Discrepancy(BaseModel):
    """A rule firing. Severity and confidence come from the rule, never from a model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    discrepancy_id: str = Field(min_length=6)
    rule_id: str = Field(min_length=3)
    kind: DiscrepancyKind
    severity: Severity
    subject_id: str = Field(min_length=1)
    attribute: Attribute | None = None
    span_seen: TimeSpan | None = None
    span_said: TimeSpan | None = None
    evidence_refs: tuple[str, ...] = ()
    det_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    note: str = ""


def make_discrepancy_id(
    rule_id: str,
    subject_id: str,
    attribute: Attribute | None,
    span_said: TimeSpan | None,
    span_seen: TimeSpan | None,
) -> str:
    return _hash(
        rule_id,
        subject_id,
        attribute.value if attribute else "",
        f"{span_said.t_start_s:.3f}" if span_said else "",
        f"{span_seen.t_start_s:.3f}" if span_seen else "",
    )


class Finding(BaseModel):
    """A discrepancy after deterministic adjudication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str = Field(min_length=6)
    discrepancy: Discrepancy
    status: FindingStatus = "open"
    rationale: str = ""

    @property
    def severity(self) -> Severity:
        return self.discrepancy.severity

    @property
    def subject_id(self) -> str:
        return self.discrepancy.subject_id


def make_finding_id(discrepancy_id: str) -> str:
    return _hash("finding", discrepancy_id)


class SubjectRef(BaseModel):
    """One subject in the run, and the reasons it is there."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str = Field(min_length=1)
    seen: bool = False
    said: bool = False
    expected: bool = False


class ChangeEvent(BaseModel):
    """A visible change the vision model noticed on a motion keyframe.

    Only used for optional omission findings: "something moved that you never
    mentioned". Kept separate from ``Assertion`` because it is not a claim about a
    known attribute, it is a hint that a subject exists.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    keyframe_id: str = Field(min_length=1)
    span: TimeSpan
    subject_id: str = Field(min_length=1)
    description: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class InteractionProposal(BaseModel):
    """What the camera thinks the speaker was touching when they said "this".

    A proposal, not a binding. ``resolution.py`` decides whether it is conclusive.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    keyframe_id: str = Field(min_length=1)
    span: TimeSpan
    object_hint: str = Field(min_length=1)
    note: str = ""


class ResolutionRecord(BaseModel):
    """Why a pronoun did or did not become a subject. Explanation, not control flow."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=6)
    resolved_subject_id: str | None = None
    source_keyframe_id: str | None = None
    note: str = ""


class ReconcileStats(BaseModel):
    """Cheap signals for evals and the run summary. Counts, not opinions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n_claims: int = 0
    n_observations: int = 0
    n_discrepancies: int = 0
    counts_by_rule: dict[str, int] = Field(default_factory=dict)
    counts_by_severity: dict[str, int] = Field(default_factory=dict)
