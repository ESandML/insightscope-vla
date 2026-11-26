"""Rules that only run when a checklist exists.

A checklist states what the task was supposed to be. Without one there is no notion
of "out of order" or "missing", so these rules are gated off rather than guessed at.
"""

from __future__ import annotations

from itertools import pairwise

from insightscope.domain.models import Assertion, Discrepancy
from insightscope.domain.ontology import Attribute
from insightscope.reconcile.context import RuleContext
from insightscope.reconcile.rules._util import claim_discrepancy, subject_discrepancy


def step_unsupported(ctx: RuleContext) -> list[Discrepancy]:
    """R-STEP-001: 'I unplugged it' with no frame showing the completion."""
    found: list[Discrepancy] = []
    for claim in ctx.claims:
        if claim.attribute is not Attribute.STEP_COMPLETED or claim.value is not True:
            continue
        if not ctx.covered(claim.span):
            continue
        matches = ctx.matches(claim)
        if any(match.value is True for match in matches):
            continue
        found.append(
            claim_discrepancy(
                "R-STEP-001",
                "unsupported",
                "major",
                claim,
                observation=matches[0] if matches else None,
                det_confidence=0.75,
                note="step claimed with no visual support",
            )
        )
    return found


def step_order(ctx: RuleContext) -> list[Discrepancy]:
    """R-STEP-002: steps happen out of the order the spec allows.

    Spoken claims take precedence when present. With no speech — a silent Process or
    Spec run — the order of ``step_completed=True`` observations decides, using the
    first keyframe that shows each step.
    """
    checklist = ctx.config.checklist
    if checklist is None or len(checklist.steps) < 2:
        return []

    order = {step_id: index for index, step_id in enumerate(checklist.step_ids())}

    claimed = [
        claim
        for claim in ctx.claims
        if claim.attribute is Attribute.STEP_COMPLETED
        and claim.value is True
        and claim.subject_id in order
    ]
    if claimed:
        claimed.sort(key=lambda claim: (claim.span.t_start_s, claim.subject_id))
        return [
            claim_discrepancy(
                "R-STEP-002",
                "sequence_violation",
                "major",
                earlier,
                det_confidence=0.85,
                note=(
                    f"{earlier.subject_id} was said before {later.subject_id}, "
                    "but comes later in the spec"
                ),
            )
            for earlier, later in pairwise(claimed)
            if order[earlier.subject_id] > order[later.subject_id]
        ]

    first_seen: dict[str, Assertion] = {}
    for observation in ctx.observations:
        if (
            observation.attribute is not Attribute.STEP_COMPLETED
            or observation.value is not True
            or observation.subject_id not in order
        ):
            continue
        current = first_seen.get(observation.subject_id)
        if current is None or observation.span.t_start_s < current.span.t_start_s:
            first_seen[observation.subject_id] = observation

    visual = sorted(
        first_seen.values(),
        key=lambda item: (item.span.t_start_s, item.subject_id),
    )
    return [
        subject_discrepancy(
            "R-STEP-002",
            "sequence_violation",
            "major",
            earlier.subject_id,
            attribute=Attribute.STEP_COMPLETED,
            span_seen=earlier.span,
            evidence_refs=earlier.evidence_refs,
            det_confidence=0.75,
            note=(
                f"{earlier.subject_id} appears before {later.subject_id} in the video, "
                "but comes later in the spec"
            ),
        )
        for earlier, later in pairwise(visual)
        if order[earlier.subject_id] > order[later.subject_id]
    ]


def step_missing(ctx: RuleContext) -> list[Discrepancy]:
    """R-STEP-003: a checklist step with no claim and no visual support."""
    checklist = ctx.config.checklist
    if checklist is None:
        return []

    said = {
        claim.subject_id
        for claim in ctx.claims
        if claim.attribute is Attribute.STEP_COMPLETED and claim.value is True
    }
    seen = {
        observation.subject_id
        for observation in ctx.observations
        if observation.attribute is Attribute.STEP_COMPLETED and observation.value is True
    }

    found: list[Discrepancy] = []
    for step in checklist.steps:
        if step.step_id in said or step.step_id in seen:
            continue
        found.append(
            subject_discrepancy(
                "R-STEP-003",
                "missing_step",
                "major",
                step.step_id,
                attribute=Attribute.STEP_COMPLETED,
                det_confidence=0.7,
                note="step in checklist with no claim and no visual support",
            )
        )
    return found
