"""Rules about object state: presence, open/closed, count, location.

Each rule only fires when the evidence actually covers the moment in question. If the
window was not observed the rule stays silent and ``R-COVER-001`` explains the gap
instead: "we did not look" must never be reported as "it was not there".
"""

from __future__ import annotations

from insightscope.domain.models import Discrepancy, Severity
from insightscope.domain.ontology import Attribute
from insightscope.reconcile.context import RuleContext
from insightscope.reconcile.rules._util import claim_discrepancy

# open <-> ajar <-> closed: adjacent states are a nuance, opposite states a conflict.
_STATE_DISTANCE: dict[frozenset[str], int] = {
    frozenset({"open", "ajar"}): 1,
    frozenset({"ajar", "closed"}): 1,
    frozenset({"open", "closed"}): 2,
}


def said_present_seen_absent(ctx: RuleContext) -> list[Discrepancy]:
    """R-PRES-001: 'the mug is on the tray' but every frame says otherwise."""
    return _presence_rule(
        ctx,
        claimed=True,
        rule_id="R-PRES-001",
        note="claimed present, every observation disagrees",
    )


def said_absent_seen_present(ctx: RuleContext) -> list[Discrepancy]:
    """R-PRES-002: 'I put the mug away' but it is still in frame."""
    return _presence_rule(
        ctx,
        claimed=False,
        rule_id="R-PRES-002",
        note="claimed absent, every observation disagrees",
    )


def _presence_rule(
    ctx: RuleContext,
    *,
    claimed: bool,
    rule_id: str,
    note: str,
) -> list[Discrepancy]:
    found: list[Discrepancy] = []
    for claim in ctx.claims:
        if claim.attribute is not Attribute.PRESENCE or claim.value is not claimed:
            continue
        if not ctx.covered(claim.span):
            continue
        matches = ctx.matches(claim)
        if not matches:
            continue
        if any(match.value is claimed for match in matches):
            continue  # at least one frame agrees: contradictory frames, not a conflict
        found.append(
            claim_discrepancy(
                rule_id,
                "contradiction",
                "major",
                claim,
                observation=matches[0],
                det_confidence=0.9,
                note=note,
            )
        )
    return found


def open_closed_mismatch(ctx: RuleContext) -> list[Discrepancy]:
    """R-STATE-001: lid state disagrees. Open vs closed is major; ajar is a nuance."""
    found: list[Discrepancy] = []
    for claim in ctx.claims:
        if claim.attribute is not Attribute.OPEN_CLOSED:
            continue
        if not ctx.covered(claim.span):
            continue
        matches = ctx.matches(claim)
        if not matches:
            continue
        if any(match.value == claim.value for match in matches):
            continue
        distance = max(_state_distance(str(claim.value), str(match.value)) for match in matches)
        severity: Severity = "major" if distance >= 2 else "minor"
        found.append(
            claim_discrepancy(
                "R-STATE-001",
                "contradiction",
                severity,
                claim,
                observation=matches[0],
                det_confidence=0.85 if distance >= 2 else 0.6,
                note=f"said {claim.value!r}, saw {sorted({str(m.value) for m in matches})}",
            )
        )
    return found


def _state_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    return _STATE_DISTANCE.get(frozenset({left, right}), 2)


def count_mismatch(ctx: RuleContext) -> list[Discrepancy]:
    """R-COUNT-001: 'there are two pens' versus a different number in frame."""
    return _value_mismatch(
        ctx,
        attribute=Attribute.COUNT,
        rule_id="R-COUNT-001",
        severity="major",
        det_confidence=0.8,
    )


def location_mismatch(ctx: RuleContext) -> list[Discrepancy]:
    """R-LOC-001: place names disagree. Minor, because region naming is noisy."""
    return _value_mismatch(
        ctx,
        attribute=Attribute.LOCATION,
        rule_id="R-LOC-001",
        severity="minor",
        det_confidence=0.6,
    )


def _value_mismatch(
    ctx: RuleContext,
    *,
    attribute: Attribute,
    rule_id: str,
    severity: Severity,
    det_confidence: float,
) -> list[Discrepancy]:
    found: list[Discrepancy] = []
    for claim in ctx.claims:
        if claim.attribute is not attribute:
            continue
        if not ctx.covered(claim.span):
            continue
        matches = ctx.matches(claim)
        if not matches or any(match.value == claim.value for match in matches):
            continue
        found.append(
            claim_discrepancy(
                rule_id,
                "value_mismatch",
                severity,
                claim,
                observation=matches[0],
                det_confidence=det_confidence,
                note=f"said {claim.value!r}, saw {sorted({str(m.value) for m in matches})}",
            )
        )
    return found
