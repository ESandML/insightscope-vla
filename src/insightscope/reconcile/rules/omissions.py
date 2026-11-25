"""Optional omission detection.

Off by default. With a camera pointed at a desk, background motion is constant, and a
report that flags every chair movement trains people to ignore the report. Enable it
per run when the interesting question is "what did you do that you did not mention?".
"""

from __future__ import annotations

from insightscope.domain.aliases import UNSPECIFIED_TARGET
from insightscope.domain.models import ChangeEvent, Discrepancy
from insightscope.reconcile.context import RuleContext
from insightscope.reconcile.rules._util import subject_discrepancy


def omitted_change(ctx: RuleContext) -> list[Discrepancy]:
    """R-OMIT-001: a visible change to a subject nobody talked about."""
    said = set(ctx.registry.said_ids())
    first_change: dict[str, ChangeEvent] = {}
    for change in sorted(ctx.changes, key=lambda item: (item.span.t_start_s, item.subject_id)):
        if change.subject_id in said or change.subject_id == UNSPECIFIED_TARGET:
            continue
        first_change.setdefault(change.subject_id, change)

    return [
        subject_discrepancy(
            "R-OMIT-001",
            "omission",
            "info",
            subject_id,
            span_seen=change.span,
            evidence_refs=(change.keyframe_id,),
            det_confidence=0.5,
            note=change.description or "visible change was never mentioned",
        )
        for subject_id, change in sorted(first_change.items())
    ]
