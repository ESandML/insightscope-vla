"""Deterministic fake clients for the offline graph.

Two knobs make them useful for testing routing rather than just happy paths:

* ``drafts`` and ``critiques`` are consumed in order and then repeat, so a test can
  say "reject once, then accept" without a model server.
* ``fail`` injects a :class:`ClientError` on the *n*-th call of a named method,
  which is how the escalation path gets covered.

``calls`` records the order of method invocations so a test can assert that a repair
actually happened instead of inferring it from the output.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from insightscope.clients.base import (
    ClaimsRequest,
    ClientError,
    CritiqueRequest,
    SynthesisRequest,
    VisionRequest,
)
from insightscope.contracts.extraction import ClaimBatch, ClaimItem, KeyframeAnalysis
from insightscope.contracts.report import Critique, ReportDraft

DraftFactory = Callable[[SynthesisRequest], ReportDraft]


def draft_citing_all(markdown: str | None = None) -> DraftFactory:
    """A draft that cites every finding, so validation passes on the first try.

    With no findings it says so. A stub that always claims disagreement would make a
    clean report contradict itself, and the CLI shows this text to a human.
    """

    def build(request: SynthesisRequest) -> ReportDraft:
        if markdown is not None:
            narrative = markdown
        elif request.findings:
            narrative = "The camera and the transcript disagree in places."
        else:
            narrative = "No conflicts were found between the transcript and the keyframes."
        return ReportDraft(
            markdown=narrative,
            cited_finding_ids=[finding.finding_id for finding in request.findings],
        )

    return build


class FakeTextClient:
    def __init__(
        self,
        *,
        claims: Mapping[str, Sequence[ClaimItem]] | None = None,
        drafts: Sequence[DraftFactory] | None = None,
        critiques: Sequence[Critique] | None = None,
        fail: Mapping[str, int] | None = None,
    ) -> None:
        self._claims = {text: list(items) for text, items in (claims or {}).items()}
        self._drafts: list[DraftFactory] = list(drafts or [draft_citing_all()])
        self._critiques: list[Critique] = list(critiques or [Critique(verdict="accept")])
        self._fail = dict(fail or {})
        self._draft_calls = 0
        self._critique_calls = 0
        self.calls: list[str] = []

    def _enter(self, name: str) -> None:
        self.calls.append(name)
        remaining = self._fail.get(name, 0)
        if remaining > 0:
            self._fail[name] = remaining - 1
            raise ClientError(name, f"scripted failure in {name}")

    async def extract_claims(self, request: ClaimsRequest) -> ClaimBatch:
        self._enter("extract_claims")
        return ClaimBatch(claims=list(self._claims.get(request.utterance.text, ())))

    async def synthesize(self, request: SynthesisRequest) -> ReportDraft:
        self._enter("synthesize")
        factory = self._drafts[min(self._draft_calls, len(self._drafts) - 1)]
        self._draft_calls += 1
        return factory(request)

    async def critique(self, request: CritiqueRequest) -> Critique:
        self._enter("critique")
        critique = self._critiques[min(self._critique_calls, len(self._critiques) - 1)]
        self._critique_calls += 1
        return critique


class FakeVisionClient:
    def __init__(
        self,
        *,
        analyses: Mapping[str, KeyframeAnalysis] | None = None,
        fail: Mapping[str, int] | None = None,
    ) -> None:
        self._analyses = dict(analyses or {})
        self._fail = dict(fail or {})
        self.calls: list[str] = []

    async def analyse(self, request: VisionRequest) -> KeyframeAnalysis:
        self.calls.append(request.keyframe.keyframe_id)
        remaining = self._fail.get("analyse", 0)
        if remaining > 0:
            self._fail["analyse"] = remaining - 1
            raise ClientError("analyse", "scripted vision failure")
        return self._analyses.get(
            request.keyframe.keyframe_id,
            KeyframeAnalysis(keyframe_id=request.keyframe.keyframe_id),
        )
