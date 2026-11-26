"""Extraction nodes: transcript first, then vision, because vision needs the targets.

Both nodes keep one hard rule: a model's output becomes an ``Assertion`` only if the
text it cites actually exists in the evidence. Quotes are checked here, in Python,
not trusted from the model.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from insightscope.clients.base import (
    ClaimsRequest,
    ClientError,
    TextClient,
    VisionClient,
    VisionRequest,
)
from insightscope.contracts.extraction import KeyframeAnalysis
from insightscope.domain.aliases import UNSPECIFIED_TARGET
from insightscope.domain.models import (
    Assertion,
    ChangeEvent,
    InteractionProposal,
    KeyframeRef,
    Provenance,
    make_assertion_id,
)
from insightscope.domain.ontology import Attribute
from insightscope.graph.nodes._common import (
    NodeUpdate,
    alias_table,
    attempt,
    cycle_of,
    failed,
)
from insightscope.graph.state import AuditState, NodeError

Node = Callable[[AuditState], Awaitable[NodeUpdate]]


def _quote_present(quote: str, text: str) -> bool:
    """Case- and whitespace-insensitive containment check."""
    return " ".join(quote.casefold().split()) in " ".join(text.casefold().split())


def _dedupe(assertions: list[Assertion]) -> list[Assertion]:
    by_id = {assertion.assertion_id: assertion for assertion in assertions}
    return sorted(
        by_id.values(),
        key=lambda a: (a.span.t_start_s, a.subject_id, a.attribute.value),
    )


def make_extract_claims(client: TextClient) -> Node:
    """One call per utterance. The utterance's time span becomes the claim's span."""

    async def node(state: AuditState) -> NodeUpdate:
        evidence = state["evidence"]
        config = state["config"]
        aliases = alias_table(config)
        issues = tuple(state.get("pending_issues") or ())
        cycle = cycle_of(state)

        claims: list[Assertion] = []
        errors: list[NodeError] = []

        for utterance in evidence.utterances:
            try:
                batch = await client.extract_claims(
                    ClaimsRequest(utterance=utterance, previous_issues=issues)
                )
            except ClientError as exc:
                return failed("extract_claims", exc, cycle)

            for item in batch.claims:
                if not _quote_present(item.quote, utterance.text):
                    errors.append(
                        NodeError(
                            node="extract_claims",
                            code="quote_not_found",
                            message=f"{utterance.utterance_id}: {item.quote[:60]!r}",
                        )
                    )
                    continue
                subject = aliases.resolve(item.subject)
                span = utterance.span
                claims.append(
                    Assertion(
                        assertion_id=make_assertion_id(
                            "acoustic", subject, item.attribute, item.value, span
                        ),
                        modality="acoustic",
                        subject_id=subject,
                        attribute=item.attribute,
                        value=item.value,
                        span=span,
                        evidence_refs=(utterance.utterance_id,),
                        confidence=0.7,
                        provenance=Provenance(
                            model=config.models.text,
                            prompt_version=client.prompt_version("extract_claims"),
                        ),
                    )
                )

        return {
            "claims": _dedupe(claims),
            "errors": errors,
            "attempts": [attempt("extract_claims", cycle)],
            "pending_issues": [],
            "trace": ["extract_claims"],
            "status": "extracting",
        }

    return node


def make_extract_observations(client: VisionClient) -> Node:
    """One call per keyframe, bounded by ``max_concurrency``.

    Targets are the (subject, attribute) pairs the transcript asked about, so the
    vision model answers specific questions instead of describing the scene.
    """

    async def node(state: AuditState) -> NodeUpdate:
        evidence = state["evidence"]
        config = state["config"]
        aliases = alias_table(config)
        issues = tuple(state.get("pending_issues") or ())
        cycle = cycle_of(state)

        claims = state.get("claims") or []
        target_set = {
            (claim.subject_id, claim.attribute)
            for claim in claims
            if claim.subject_id != UNSPECIFIED_TARGET
        }

        # A Process/Spec run may have no transcript at all. The spec still tells the
        # camera what to look at: objects by presence, steps by completion.
        checklist = config.checklist
        if checklist is not None:
            for name in checklist.expected_objects:
                target_set.add((aliases.resolve(name), Attribute.PRESENCE))
            for step in checklist.steps:
                target_set.add((step.step_id, Attribute.STEP_COMPLETED))

        targets = tuple(sorted(target_set, key=lambda pair: (pair[0], pair[1].value)))
        requested = sorted({subject for subject, _ in targets})

        semaphore = asyncio.Semaphore(config.max_concurrency)

        async def analyse(keyframe: KeyframeRef) -> KeyframeAnalysis:
            async with semaphore:
                return await client.analyse(
                    VisionRequest(
                        keyframe=keyframe,
                        targets=targets,
                        previous_issues=issues,
                    )
                )

        results = await asyncio.gather(
            *(analyse(keyframe) for keyframe in evidence.keyframes),
            return_exceptions=True,
        )

        analyses: list[KeyframeAnalysis] = []
        for result in results:
            if isinstance(result, ClientError):
                return failed("extract_observations", result, cycle)
            if isinstance(result, BaseException):
                raise result
            analyses.append(result)

        observations: list[Assertion] = []
        proposals: list[InteractionProposal] = []
        changes: list[ChangeEvent] = []

        # Pair by position, not by the model's echoed id: a drifting id must not
        # attach an observation to a different moment.
        for keyframe, analysis in zip(evidence.keyframes, analyses, strict=True):
            for verified in analysis.verified:
                subject = aliases.resolve(verified.subject)
                observations.append(
                    Assertion(
                        assertion_id=make_assertion_id(
                            "vision", subject, verified.attribute, verified.value, keyframe.span
                        ),
                        modality="vision",
                        subject_id=subject,
                        attribute=verified.attribute,
                        value=verified.value,
                        span=keyframe.span,
                        evidence_refs=(keyframe.keyframe_id,),
                        confidence=verified.confidence,
                        provenance=Provenance(
                            model=config.models.vision,
                            prompt_version=client.prompt_version("verify_keyframe"),
                        ),
                    )
                )
            if analysis.interacted_object:
                proposals.append(
                    InteractionProposal(
                        keyframe_id=keyframe.keyframe_id,
                        span=keyframe.span,
                        object_hint=analysis.interacted_object,
                        note=analysis.interaction_note,
                    )
                )
            for change in analysis.observed_changes:
                changes.append(
                    ChangeEvent(
                        keyframe_id=keyframe.keyframe_id,
                        span=keyframe.span,
                        subject_id=aliases.resolve(change.subject),
                        description=change.description,
                        confidence=change.confidence,
                    )
                )

        return {
            "observations": _dedupe(observations),
            "proposals": proposals,
            "changes": changes,
            "requested_subjects": requested,
            "attempts": [attempt("extract_observations", cycle)],
            "trace": ["extract_observations"],
            "status": "extracting",
        }

    return node


def attributes_for(claims: list[Assertion]) -> tuple[Attribute, ...]:
    """Which attributes were asked about; exposed for prompt construction later."""
    return tuple(sorted({claim.attribute for claim in claims}, key=lambda a: a.value))
