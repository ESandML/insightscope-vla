"""The read-only bundle every rule receives.

Building this once keeps rules small and free of bookkeeping: a rule asks "what did
the camera see for this claim?" and "was that window even observed?", and nothing
else has to know how alignments are indexed.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from insightscope.config import RunConfig
from insightscope.domain.models import (
    Alignment,
    Assertion,
    ChangeEvent,
    EvidenceManifest,
    TimeSpan,
)
from insightscope.domain.registry import SubjectRegistry


@dataclass(frozen=True, slots=True)
class RuleContext:
    """Everything a rule may look at. Deliberately not the graph, and not a client."""

    claims: tuple[Assertion, ...]
    observations: tuple[Assertion, ...]
    changes: tuple[ChangeEvent, ...]
    alignments: tuple[Alignment, ...]
    evidence: EvidenceManifest
    registry: SubjectRegistry
    config: RunConfig
    requested_subjects: frozenset[str] | None
    matches_by_claim: Mapping[str, tuple[Assertion, ...]] = field(repr=False)

    def matches(self, claim: Assertion) -> tuple[Assertion, ...]:
        """Observations aligned to this claim (all of them, not just the closest)."""
        return self.matches_by_claim.get(claim.assertion_id, ())

    def covered(self, span: TimeSpan) -> bool:
        """True when at least one keyframe observed this moment."""
        return self.evidence.has_evidence_within(span, self.config.alignment.tolerance_s)


def build_context(
    *,
    claims: Sequence[Assertion],
    observations: Sequence[Assertion],
    changes: Sequence[ChangeEvent],
    alignments: Sequence[Alignment],
    evidence: EvidenceManifest,
    registry: SubjectRegistry,
    config: RunConfig,
    requested_subjects: Sequence[str] | None,
) -> RuleContext:
    by_id = {observation.assertion_id: observation for observation in observations}
    grouped: dict[str, list[Assertion]] = defaultdict(list)
    for alignment in alignments:
        if alignment.observation_id is None:
            continue
        observation = by_id.get(alignment.observation_id)
        if observation is not None:
            grouped[alignment.claim_id].append(observation)

    frozen_matches: dict[str, tuple[Assertion, ...]] = {
        claim_id: tuple(sorted(items, key=lambda item: item.assertion_id))
        for claim_id, items in grouped.items()
    }

    return RuleContext(
        claims=tuple(claims),
        observations=tuple(observations),
        changes=tuple(changes),
        alignments=tuple(alignments),
        evidence=evidence,
        registry=registry,
        config=config,
        requested_subjects=(
            frozenset(requested_subjects) if requested_subjects is not None else None
        ),
        matches_by_claim=frozen_matches,
    )
