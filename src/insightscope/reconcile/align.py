"""Pairing claims with observations in time.

Alignment answers one question: which observations are close enough to a claim that
they could be about the same moment? It never judges agreement — that is the rules'
job. Being a separate step means the window is one testable function rather than a
condition repeated in ten rules.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from insightscope.domain.aliases import UNSPECIFIED_TARGET
from insightscope.domain.models import Alignment, Assertion, TimeSpan
from insightscope.domain.ontology import Attribute


def align_claims(
    *,
    claims: Sequence[Assertion],
    observations: Sequence[Assertion],
    window: tuple[float, float],
) -> tuple[Alignment, ...]:
    """Return every plausible said/seen pair, closest first per claim.

    ``window`` is ``(before_s, after_s)``: how far before the claim an observation
    may sit, and how far after. Both default to 3 s. The pair is only recorded when
    subject *and* attribute match, so a claim about the lid is never compared with an
    observation about the mug.
    """
    before_s, after_s = window
    index: dict[tuple[str, Attribute], list[Assertion]] = defaultdict(list)
    for observation in observations:
        if observation.subject_id == UNSPECIFIED_TARGET:
            continue
        index[(observation.subject_id, observation.attribute)].append(observation)

    rows: list[Alignment] = []
    for claim in claims:
        if claim.subject_id == UNSPECIFIED_TARGET:
            continue
        candidates = [
            observation
            for observation in index.get((claim.subject_id, claim.attribute), ())
            if _within_window(claim.span, observation.span, before_s=before_s, after_s=after_s)
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda obs: (abs(obs.span.mid_s - claim.span.mid_s), obs.assertion_id))
        for rank, observation in enumerate(candidates):
            rows.append(
                Alignment(
                    claim_id=claim.assertion_id,
                    observation_id=observation.assertion_id,
                    delta_s=round(observation.span.mid_s - claim.span.mid_s, 3),
                    matched=rank == 0,
                )
            )

    rows.sort(key=lambda row: (row.claim_id, abs(row.delta_s or 0.0), row.observation_id or ""))
    return tuple(rows)


def _within_window(
    claim_span: TimeSpan,
    observation_span: TimeSpan,
    *,
    before_s: float,
    after_s: float,
) -> bool:
    if observation_span.t_end_s <= claim_span.t_start_s:
        return claim_span.t_start_s - observation_span.t_end_s <= before_s
    if observation_span.t_start_s >= claim_span.t_end_s:
        return observation_span.t_start_s - claim_span.t_end_s <= after_s
    return True
