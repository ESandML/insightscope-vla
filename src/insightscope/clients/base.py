"""The interfaces nodes depend on.

Nodes never import a provider SDK. They ask a ``TextClient`` or ``VisionClient`` for a
structured object, and validation has already happened by the time they get it. That
is what lets Phase 1 run the whole graph offline against fakes, and what will let
Phase 2 swap Ollama for vLLM by changing one class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from insightscope.contracts.extraction import ClaimBatch, KeyframeAnalysis
from insightscope.contracts.report import Critique, Issue, ReportDraft
from insightscope.domain.models import EvidenceManifest, Finding, KeyframeRef, Utterance
from insightscope.domain.ontology import Attribute


class ClientError(RuntimeError):
    """A model call failed in a way the graph cannot fix by reading it differently."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class ClaimsRequest:
    utterance: Utterance
    previous_issues: tuple[Issue, ...] = ()


@dataclass(frozen=True, slots=True)
class VisionRequest:
    keyframe: KeyframeRef
    targets: tuple[tuple[str, Attribute], ...] = field(default_factory=tuple)
    previous_issues: tuple[Issue, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class SynthesisRequest:
    findings: tuple[Finding, ...]
    evidence: EvidenceManifest
    previous_markdown: str | None = None
    issues: tuple[Issue, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CritiqueRequest:
    draft: ReportDraft
    findings: tuple[Finding, ...]


class TextClient(Protocol):
    """Extraction, drafting, and critique. One object because they share a model."""

    async def extract_claims(self, request: ClaimsRequest) -> ClaimBatch: ...

    async def synthesize(self, request: SynthesisRequest) -> ReportDraft: ...

    async def critique(self, request: CritiqueRequest) -> Critique: ...


class VisionClient(Protocol):
    """One keyframe in, one structured analysis out."""

    async def analyse(self, request: VisionRequest) -> KeyframeAnalysis: ...
