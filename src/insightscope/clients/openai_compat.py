"""OpenAI-compatible client for local models (Ollama today, vLLM unchanged).

The only place that knows Ollama exists. It speaks the OpenAI chat-completions API and
delegates schema enforcement to Instructor in ``Mode.JSON``: every response is parsed
into the Pydantic contract before it reaches a node, and malformed JSON is retried a
bounded number of times *at this layer*. That is a different retry from the graph's,
which repairs reasoning rather than syntax.

Imports of ``openai``/``instructor`` are lazy so the core install (and the whole test
suite) works without the ``llm`` extra.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, TypeVar, cast

from pydantic import BaseModel

from insightscope.clients.base import (
    ClaimsRequest,
    ClientError,
    CritiqueRequest,
    SynthesisRequest,
    VisionRequest,
)
from insightscope.clients.prompts import PromptLibrary, render
from insightscope.config import Settings
from insightscope.contracts.extraction import ClaimBatch, KeyframeAnalysis
from insightscope.contracts.report import Critique, Issue, ReportDraft
from insightscope.domain.checklist import ChecklistSpec
from insightscope.domain.models import Finding, Utterance
from insightscope.domain.ontology import Attribute

SYSTEM_MESSAGE = (
    "You are a precise component in an audit pipeline. Follow the instructions exactly, "
    "use only the evidence given, and return only the requested structured output."
)

_SYNTHESIS_EXAMPLE_ID = "f_example"

_ResponseModel = TypeVar("_ResponseModel", bound=BaseModel)


class ModelClientUnavailable(RuntimeError):
    """The optional model dependency is not installed."""


class OllamaClients:
    """One object implementing the text, vision, and checklist protocols."""

    def __init__(
        self,
        *,
        settings: Settings,
        prompts: PromptLibrary | None = None,
        client: Any | None = None,
        schema_retries: int = 2,
    ) -> None:
        self._settings = settings
        self._prompts = prompts or PromptLibrary()
        self._schema_retries = schema_retries
        self._client = client if client is not None else _build_instructor_client(settings)

    def prompt_version(self, name: str) -> str:
        return self._prompts.load(name).version

    # -- text ------------------------------------------------------------

    async def extract_claims(self, request: ClaimsRequest) -> ClaimBatch:
        prompt = self._prompts.load("extract_claims")
        rendered = render(
            prompt,
            attributes=", ".join(attribute.value for attribute in Attribute),
            start=f"{request.utterance.span.t_start_s:.1f}",
            end=f"{request.utterance.span.t_end_s:.1f}",
            utterance=request.utterance.text,
            issues=_format_issues(request.previous_issues),
        )
        return await self._create(
            ClaimBatch,
            model=self._settings.text_model,
            messages=_text_messages(rendered),
        )

    async def synthesize(self, request: SynthesisRequest) -> ReportDraft:
        prompt = self._prompts.load("synthesize_report")
        rendered = render(
            prompt,
            example_id=_SYNTHESIS_EXAMPLE_ID,
            keyframe_count=len(request.evidence.keyframes),
            transcript_mode=request.evidence.transcript_mode,
            findings=_format_findings(request.findings),
            previous=request.previous_markdown or "(none)",
            issues=_format_issues(request.issues),
        )
        return await self._create(
            ReportDraft,
            model=self._settings.text_model,
            messages=_text_messages(rendered),
        )

    async def critique(self, request: CritiqueRequest) -> Critique:
        prompt = self._prompts.load("critique_report")
        rendered = render(
            prompt,
            findings=_format_findings(request.findings),
            draft=_format_draft(request.draft),
        )
        return await self._create(
            Critique,
            model=self._settings.text_model,
            messages=_text_messages(rendered),
        )

    async def generate_checklist(self, description: str) -> ChecklistSpec:
        prompt = self._prompts.load("generate_checklist")
        rendered = render(prompt, description=description)
        return await self._create(
            ChecklistSpec,
            model=self._settings.text_model,
            messages=_text_messages(rendered),
        )

    # -- vision ----------------------------------------------------------

    async def analyse(self, request: VisionRequest) -> KeyframeAnalysis:
        prompt = self._prompts.load("verify_keyframe")
        rendered = render(
            prompt,
            targets=_format_targets(request.targets),
            time=f"{request.keyframe.span.t_start_s:.1f}",
            scene_hint="",
        )
        image_url = encode_image(Path(request.keyframe.uri))
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": rendered},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ]
        return await self._create(
            KeyframeAnalysis,
            model=self._settings.vision_model,
            messages=messages,
        )

    # -- transport -------------------------------------------------------

    async def _create(
        self,
        response_model: type[_ResponseModel],
        *,
        model: str,
        messages: list[dict[str, Any]],
    ) -> _ResponseModel:
        try:
            result = await self._client.chat.completions.create(
                model=model,
                messages=messages,
                response_model=response_model,
                max_retries=self._schema_retries,
                timeout=self._settings.llm_timeout_s,
                temperature=0.0,
            )
        except Exception as exc:
            raise ClientError(
                "model_call_failed",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        return cast(_ResponseModel, result)


def _build_instructor_client(settings: Settings) -> Any:
    try:
        import instructor
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise ModelClientUnavailable(
            "the Ollama client needs the llm extra: uv sync --extra llm"
        ) from exc

    http = AsyncOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout_s,
    )
    # JSON mode rather than tool calling: schema validation works the same on every
    # model Ollama serves, including ones with weak function-calling support.
    return instructor.from_openai(http, mode=instructor.Mode.JSON)


def _text_messages(rendered: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {"role": "user", "content": rendered},
    ]


def encode_image(path: Path) -> str:
    """Data URI for the OpenAI multimodal message format."""
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def _format_targets(targets: tuple[tuple[str, Attribute], ...]) -> str:
    if not targets:
        return "(none listed: report only obvious changes)"
    return "\n".join(f"- {subject} / {attribute.value}" for subject, attribute in targets)


def _format_findings(findings: tuple[Finding, ...]) -> str:
    if not findings:
        return "(no findings)"
    lines = []
    for finding in findings:
        discrepancy = finding.discrepancy
        said = (
            f"{discrepancy.said_value} @ {discrepancy.span_said.t_start_s:.1f}s"
            if discrepancy.span_said
            else "-"
        )
        seen = (
            f"{discrepancy.seen_value} @ {discrepancy.span_seen.t_start_s:.1f}s"
            if discrepancy.span_seen
            else "-"
        )
        lines.append(
            f"- {finding.finding_id} | {discrepancy.severity} | {discrepancy.rule_id} | "
            f"{discrepancy.subject_id} | said {said} | seen {seen} | {finding.status}"
        )
    return "\n".join(lines)


def _format_draft(draft: ReportDraft) -> str:
    citations = ", ".join(draft.cited_finding_ids) or "(none)"
    return f"{draft.markdown.strip()}\n\nCited finding ids: {citations}"


def _format_issues(issues: tuple[Issue, ...] | list[Issue]) -> str:
    if not issues:
        return "(none)"
    return "\n".join(
        f"- {issue.severity} [{issue.target}] {issue.code} ref={issue.ref}: {issue.message}"
        for issue in issues
    )


def utterance_span(utterance: Utterance) -> str:
    """Small helper used by prompts and diagnostics."""
    return f"{utterance.span.t_start_s:.1f}-{utterance.span.t_end_s:.1f}s"
