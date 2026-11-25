"""Rules about evidence coverage: what we could not check.

These are the rules that keep the rest honest. A missing keyframe is not a
contradiction, and an unanswered question is not a lie. Both are reported as
``insufficient_evidence`` with severity ``info``, and both are visible in the stats
so a run that proved very little cannot look like a run that proved a lot.
"""

from __future__ import annotations

from insightscope.domain.models import Discrepancy
from insightscope.domain.ontology import Attribute
from insightscope.reconcile.context import RuleContext
from insightscope.reconcile.rules._util import claim_discrepancy


def coverage_gap(ctx: RuleContext) -> list[Discrepancy]:
    """R-COVER-001: no keyframe observed this claim's moment at all."""
    found: list[Discrepancy] = []
    for claim in ctx.claims:
        if ctx.covered(claim.span):
            continue
        found.append(
            claim_discrepancy(
                "R-COVER-001",
                "insufficient_evidence",
                "info",
                claim,
                det_confidence=0.95,
                note="no keyframe observed this window; nothing can be concluded",
            )
        )
    return found


def not_reported(ctx: RuleContext) -> list[Discrepancy]:
    """R-COVER-002: the moment was observed, but the camera reported nothing.

    Steps are excluded on purpose: a missing step answer is what R-STEP-001 is for,
    and reporting it twice would inflate the finding count.
    """
    found: list[Discrepancy] = []
    for claim in ctx.claims:
        if claim.attribute is Attribute.STEP_COMPLETED:
            continue
        if not ctx.covered(claim.span):
            continue
        if ctx.matches(claim):
            continue
        found.append(
            claim_discrepancy(
                "R-COVER-002",
                "insufficient_evidence",
                "info",
                claim,
                det_confidence=0.6,
                note="window observed, but no observation for this subject",
            )
        )
    return found
