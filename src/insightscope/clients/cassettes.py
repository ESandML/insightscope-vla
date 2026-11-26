"""Record real model traffic once, replay it forever.

A cassette is a JSON file mapping a content key to a validated response. Keys are
derived from what the model was asked — utterance text, keyframe hash, finding ids —
not from file paths, so a cassette recorded on your laptop replays in CI where the
keyframes live somewhere else.

Replay is how the evaluation suite stays honest and offline: the same real outputs are
fed through the same deterministic rules, and any change in findings is a change in our
code, not model sampling.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from insightscope.clients.base import (
    ClaimsRequest,
    CritiqueRequest,
    SynthesisRequest,
    VisionRequest,
)
from insightscope.contracts.extraction import ClaimBatch, KeyframeAnalysis
from insightscope.contracts.report import Critique, ReportDraft
from insightscope.domain.checklist import ChecklistSpec

CASSETTE_VERSION = 1

_RESPONSE_MODELS: dict[str, type[BaseModel]] = {
    "extract_claims": ClaimBatch,
    "analyse": KeyframeAnalysis,
    "synthesize": ReportDraft,
    "critique": Critique,
    "generate_checklist": ChecklistSpec,
}


class CassetteMiss(LookupError):
    """The cassette has no entry for this request."""


class CassetteFormatError(ValueError):
    """The cassette file is not a cassette we understand."""


def payload_for(method: str, request: object) -> dict[str, Any]:
    """Stable description of a request. Paths and absolute times are deliberately absent."""
    if method == "extract_claims" and isinstance(request, ClaimsRequest):
        return {
            "utterance": request.utterance.text,
            "start": round(request.utterance.span.t_start_s, 3),
            "end": round(request.utterance.span.t_end_s, 3),
            "issues": [issue.model_dump(mode="json") for issue in request.previous_issues],
        }
    if method == "analyse" and isinstance(request, VisionRequest):
        return {
            "keyframe": request.keyframe.sha256,
            "targets": [[subject, attribute.value] for subject, attribute in request.targets],
            "issues": [issue.model_dump(mode="json") for issue in request.previous_issues],
        }
    if method == "synthesize" and isinstance(request, SynthesisRequest):
        return {
            "findings": [finding.finding_id for finding in request.findings],
            "transcript_mode": request.evidence.transcript_mode,
            "previous": _digest(request.previous_markdown or ""),
            "issues": [issue.model_dump(mode="json") for issue in request.issues],
        }
    if method == "critique" and isinstance(request, CritiqueRequest):
        return {
            "draft": _digest(request.draft.markdown),
            "citations": sorted(request.draft.cited_finding_ids),
            "findings": [finding.finding_id for finding in request.findings],
        }
    if method == "generate_checklist" and isinstance(request, str):
        return {"description": request}
    raise CassetteFormatError(f"no payload recipe for {method} with {type(request).__name__}")


def entry_key(method: str, request: object) -> str:
    encoded = json.dumps(payload_for(method, request), sort_keys=True).encode()
    return hashlib.sha256(method.encode() + b"|" + encoded).hexdigest()[:16]


class Cassette:
    def __init__(self, path: Path, entries: dict[str, dict[str, Any]] | None = None) -> None:
        self.path = path
        self.entries: dict[str, dict[str, Any]] = entries or {}

    @classmethod
    def load(cls, path: str | Path) -> Cassette:
        source = Path(path)
        if not source.exists():
            raise CassetteFormatError(f"{source}: cassette not found")
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CassetteFormatError(f"{source}: invalid JSON: {exc}") from exc
        if not isinstance(raw, dict) or raw.get("version") != CASSETTE_VERSION:
            raise CassetteFormatError(f"{source}: unsupported cassette version")
        entries = raw.get("entries")
        if not isinstance(entries, dict):
            raise CassetteFormatError(f"{source}: 'entries' must be an object")
        return cls(source, entries)

    def save(self, path: str | Path | None = None) -> Path:
        destination = Path(path) if path is not None else self.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CASSETTE_VERSION,
            "entries": dict(sorted(self.entries.items())),
        }
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return destination

    def put(self, method: str, key: str, response: BaseModel) -> None:
        self.entries[key] = {
            "method": method,
            "response": response.model_dump(mode="json"),
        }

    def get(self, method: str, key: str) -> BaseModel:
        entry = self.entries.get(key)
        if entry is None:
            raise CassetteMiss(f"no cassette entry for {method} ({key})")
        if entry.get("method") != method:
            raise CassetteMiss(f"cassette entry {key} is for {entry.get('method')}, not {method}")
        model = _RESPONSE_MODELS[method]
        return model.model_validate(entry["response"])


class CassetteRecorder:
    """Wraps a client and stores every validated response."""

    def __init__(self, inner: Any, cassette: Cassette) -> None:
        self._inner = inner
        self._cassette = cassette

    @property
    def cassette(self) -> Cassette:
        return self._cassette

    def prompt_version(self, name: str) -> str:
        return str(self._inner.prompt_version(name))

    async def extract_claims(self, request: ClaimsRequest) -> ClaimBatch:
        result = cast(ClaimBatch, await self._inner.extract_claims(request))
        self._cassette.put("extract_claims", entry_key("extract_claims", request), result)
        return result

    async def analyse(self, request: VisionRequest) -> KeyframeAnalysis:
        result = cast(KeyframeAnalysis, await self._inner.analyse(request))
        self._cassette.put("analyse", entry_key("analyse", request), result)
        return result

    async def synthesize(self, request: SynthesisRequest) -> ReportDraft:
        result = cast(ReportDraft, await self._inner.synthesize(request))
        self._cassette.put("synthesize", entry_key("synthesize", request), result)
        return result

    async def critique(self, request: CritiqueRequest) -> Critique:
        result = cast(Critique, await self._inner.critique(request))
        self._cassette.put("critique", entry_key("critique", request), result)
        return result

    async def generate_checklist(self, description: str) -> ChecklistSpec:
        result = cast(ChecklistSpec, await self._inner.generate_checklist(description))
        self._cassette.put(
            "generate_checklist", entry_key("generate_checklist", description), result
        )
        return result


class CassettePlayer:
    """Serves validated responses from a cassette. No network, no model."""

    def __init__(self, cassette: Cassette) -> None:
        self._cassette = cassette
        self.calls: list[str] = []

    def prompt_version(self, name: str) -> str:
        return f"cassette-{name}"

    async def extract_claims(self, request: ClaimsRequest) -> ClaimBatch:
        self.calls.append("extract_claims")
        response = self._cassette.get("extract_claims", entry_key("extract_claims", request))
        assert isinstance(response, ClaimBatch)
        return response

    async def analyse(self, request: VisionRequest) -> KeyframeAnalysis:
        self.calls.append("analyse")
        response = self._cassette.get("analyse", entry_key("analyse", request))
        assert isinstance(response, KeyframeAnalysis)
        return response

    async def synthesize(self, request: SynthesisRequest) -> ReportDraft:
        self.calls.append("synthesize")
        response = self._cassette.get("synthesize", entry_key("synthesize", request))
        assert isinstance(response, ReportDraft)
        return response

    async def critique(self, request: CritiqueRequest) -> Critique:
        self.calls.append("critique")
        response = self._cassette.get("critique", entry_key("critique", request))
        assert isinstance(response, Critique)
        return response

    async def generate_checklist(self, description: str) -> ChecklistSpec:
        self.calls.append("generate_checklist")
        response = self._cassette.get(
            "generate_checklist", entry_key("generate_checklist", description)
        )
        assert isinstance(response, ChecklistSpec)
        return response


def load_cassette(path: str | Path) -> Cassette:
    return Cassette.load(path)


def merge_cassettes(target: Cassette, sources: Mapping[str, Any]) -> None:
    """Combine recorded entries (used when a scenario spans several runs)."""
    for cassette in sources.values():
        if isinstance(cassette, Cassette):
            target.entries.update(cassette.entries)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]
