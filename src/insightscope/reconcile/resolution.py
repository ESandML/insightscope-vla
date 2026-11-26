"""Turning "I closed this" into a subject, or admitting that we cannot.

The vision model proposes which object the speaker was interacting with. This module
is the only place that turns a proposal into a fact, and it does so only when the
proposals agree. One candidate binds; zero or several do not. That asymmetry is the
whole point: an unresolved reference is recoverable, a wrong binding is a false
finding.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from insightscope.domain.aliases import UNSPECIFIED_TARGET, AliasTable, normalize_subject
from insightscope.domain.models import (
    Assertion,
    InteractionProposal,
    ResolutionRecord,
    make_assertion_id,
)


@dataclass(frozen=True, slots=True)
class ResolutionOutcome:
    claims: tuple[Assertion, ...]
    records: tuple[ResolutionRecord, ...]
    unresolved: tuple[str, ...]


def resolve_claims(
    *,
    claims: Sequence[Assertion],
    proposals: Sequence[InteractionProposal],
    aliases: AliasTable,
    tolerance_s: float,
) -> ResolutionOutcome:
    """Bind ``unspecified_target`` claims to the one object the camera supports."""
    resolved: list[Assertion] = []
    records: list[ResolutionRecord] = []
    unresolved: list[str] = []

    for claim in claims:
        if claim.subject_id != UNSPECIFIED_TARGET:
            resolved.append(claim)
            continue

        nearby = [
            proposal for proposal in proposals if proposal.span.overlaps(claim.span, tolerance_s)
        ]
        candidates = sorted(
            {
                subject
                for proposal in nearby
                if (subject := aliases.resolve(proposal.object_hint)) != UNSPECIFIED_TARGET
            }
        )

        if len(candidates) == 1:
            subject = candidates[0]
            rebound = claim.model_copy(
                update={
                    "subject_id": subject,
                    "assertion_id": make_assertion_id(
                        claim.modality,
                        subject,
                        claim.attribute,
                        claim.value,
                        claim.span,
                        claim.action,
                    ),
                }
            )
            resolved.append(rebound)
            records.append(
                ResolutionRecord(
                    claim_id=claim.assertion_id,
                    resolved_subject_id=subject,
                    source_keyframe_id=nearby[0].keyframe_id,
                    note=f"bound from {nearby[0].object_hint!r}"
                    if nearby[0].object_hint
                    else "bound from interaction proposal",
                )
            )
            continue

        unresolved.append(claim.assertion_id)
        resolved.append(claim)
        if candidates:
            records.append(
                ResolutionRecord(
                    claim_id=claim.assertion_id,
                    note=f"ambiguous: {', '.join(candidates)}",
                )
            )
        else:
            records.append(
                ResolutionRecord(claim_id=claim.assertion_id, note="no interacting object proposed")
            )

    return ResolutionOutcome(
        claims=tuple(resolved),
        records=tuple(records),
        unresolved=tuple(unresolved),
    )


def normalise_hint(hint: str) -> str:
    """Exposed for tests and for callers that want the same normalisation."""
    return normalize_subject(hint)


__all__ = ["ResolutionOutcome", "normalise_hint", "resolve_claims"]
