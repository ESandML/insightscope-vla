"""Rules for spoken actions that do not map to a static state.

"I stirred the coffee" has no lid to check and no place to measure. The claim carries a
normalised action, and the camera is asked that exact question; this rule compares the
two answers. It is open-ended (no spec required), unlike the step rules.
"""

from __future__ import annotations

from insightscope.domain.models import Discrepancy
from insightscope.domain.ontology import Attribute
from insightscope.reconcile.context import RuleContext
from insightscope.reconcile.rules._util import claim_discrepancy


def action_mismatch(ctx: RuleContext) -> list[Discrepancy]:
    """R-ACT-001: said the action happened (or did not) and the frames disagree.

    Alignment already pairs only assertions with the same ``(subject, action)``, so a
    "stir" claim can never be checked against a "pour" observation. When the window was
    not observed, or nothing was reported, the coverage rules speak instead of this one.
    """
    found: list[Discrepancy] = []
    for claim in ctx.claims:
        if claim.attribute is not Attribute.ACTION_COMPLETED:
            continue
        if not ctx.covered(claim.span):
            continue

        matches = [
            observation
            for observation in ctx.matches(claim)
            if observation.attribute is Attribute.ACTION_COMPLETED
            and observation.action == claim.action
        ]
        if not matches:
            continue
        if any(match.value == claim.value for match in matches):
            continue  # at least one frame agrees; contradiction would be unfair

        found.append(
            claim_discrepancy(
                "R-ACT-001",
                "contradiction",
                "major",
                claim,
                observation=matches[0],
                det_confidence=0.85,
                note=(f"action {claim.action!r}: said {claim.value}, saw {matches[0].value}"),
            )
        )
    return found
