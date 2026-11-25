"""Rules about references and unexpected subjects.

Both are honest-failure rules: they do not accuse anyone of anything, they record
that the pipeline could not establish who or what was meant.
"""

from __future__ import annotations

from insightscope.domain.aliases import UNSPECIFIED_TARGET
from insightscope.domain.models import Discrepancy
from insightscope.reconcile.context import RuleContext
from insightscope.reconcile.rules._util import claim_discrepancy, subject_discrepancy


def unresolved_reference(ctx: RuleContext) -> list[Discrepancy]:
    """R-REF-001: 'this' never resolved to exactly one object."""
    return [
        claim_discrepancy(
            "R-REF-001",
            "unresolved_reference",
            "minor",
            claim,
            det_confidence=0.9,
            note="pronoun could not be bound to a single object",
        )
        for claim in ctx.claims
        if claim.subject_id == UNSPECIFIED_TARGET
    ]


def unexpected_subject(ctx: RuleContext) -> list[Discrepancy]:
    """R-SUBJ-001: the camera described something that was never asked about.

    Skipped when the caller did not supply the requested subject list. This is an
    extraction-quality signal ("the model drifted"), not a claim about the world.
    """
    if ctx.requested_subjects is None:
        return []

    unexpected = sorted(
        {
            observation.subject_id
            for observation in ctx.observations
            if observation.subject_id not in ctx.requested_subjects
            and observation.subject_id != UNSPECIFIED_TARGET
        }
    )
    return [
        subject_discrepancy(
            "R-SUBJ-001",
            "subject_unmatched",
            "info",
            subject_id,
            det_confidence=0.4,
            note="camera reported a subject that was not requested",
        )
        for subject_id in unexpected
    ]
