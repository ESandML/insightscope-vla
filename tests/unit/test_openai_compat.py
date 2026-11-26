"""The Ollama client's request shaping, schema plumbing, and error mapping.

No network: a stub stands in for Instructor's patched client, so these tests assert
what we send and how we translate failures, which is the part we wrote.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from tests.support import claim, keyframe, manifest, observation

from insightscope.clients.base import (
    ClaimsRequest,
    ClientError,
    CritiqueRequest,
    SynthesisRequest,
    VisionRequest,
)
from insightscope.clients.openai_compat import OllamaClients, encode_image
from insightscope.clients.prompts import PromptLibrary
from insightscope.config import RunConfig, Settings
from insightscope.contracts.extraction import ClaimBatch, KeyframeAnalysis
from insightscope.contracts.report import Critique, Issue, ReportDraft
from insightscope.domain.checklist import ChecklistSpec
from insightscope.domain.models import TimeSpan, Utterance
from insightscope.domain.ontology import Attribute
from insightscope.reconcile import reconcile


class StubCompletions:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class StubClient:
    def __init__(self, completions: StubCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


def build(
    result: object, *, error: Exception | None = None
) -> tuple[OllamaClients, StubCompletions]:
    completions = StubCompletions(result, error)
    settings = Settings(_env_file=None, text_model="text-test", vision_model="vision-test")
    client = OllamaClients(
        settings=settings,
        prompts=PromptLibrary(),
        client=StubClient(completions),
    )
    return client, completions


def utterance() -> Utterance:
    return Utterance(
        utterance_id="u_0001",
        text="I closed the laptop",
        span=TimeSpan(t_start_s=1.0, t_end_s=2.0),
    )


async def test_extract_claims_sends_schema_and_prompt() -> None:
    batch = ClaimBatch()
    client, completions = build(batch)

    result = await client.extract_claims(ClaimsRequest(utterance=utterance()))

    assert result is batch
    call = completions.calls[0]
    assert call["response_model"] is ClaimBatch
    assert call["model"] == "text-test"
    assert call["max_retries"] == 2
    assert call["temperature"] == 0.0
    assert call["timeout"] == 120.0
    assert "I closed the laptop" in call["messages"][1]["content"]


async def test_prompt_version_is_the_file_hash() -> None:
    client, _ = build(ClaimBatch())
    expected = PromptLibrary().load("extract_claims").version
    assert client.prompt_version("extract_claims") == expected


async def test_analyse_embeds_a_base64_image(tmp_path: Path) -> None:
    frame_path = tmp_path / "kf.jpg"
    assert cv2.imwrite(str(frame_path), np.zeros((32, 32, 3), dtype=np.uint8))
    ref = keyframe("kf_0001", start=1.0, end=2.0)
    ref = ref.model_copy(update={"uri": str(frame_path)})

    client, completions = build(KeyframeAnalysis(keyframe_id="kf_0001"))
    await client.analyse(VisionRequest(keyframe=ref, targets=(("laptop", Attribute.OPEN_CLOSED),)))

    call = completions.calls[0]
    assert call["model"] == "vision-test"
    assert call["response_model"] is KeyframeAnalysis
    content = call["messages"][1]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "laptop / open_closed_state" in content[0]["text"]


async def test_synthesize_includes_findings_and_previous_issues() -> None:
    finding = reconcile(
        claims=[claim("laptop", Attribute.OPEN_CLOSED, "closed")],
        observations=[observation("laptop", Attribute.OPEN_CLOSED, "open")],
        evidence=manifest(),
        config=RunConfig(),
    ).findings[0]

    client, completions = build(ReportDraft(markdown="draft", cited_finding_ids=[]))
    issue = Issue(
        code="unclear", severity="major", target="synthesize", ref="report", message="cite it"
    )

    await client.synthesize(
        SynthesisRequest(
            findings=(finding,),
            evidence=manifest(),
            previous_markdown="old draft",
            issues=(issue,),
        )
    )

    user_text = completions.calls[0]["messages"][1]["content"]
    assert finding.finding_id in user_text
    assert "old draft" in user_text
    assert "cite it" in user_text


async def test_critique_includes_citations() -> None:
    client, completions = build(Critique(verdict="accept"))
    await client.critique(
        CritiqueRequest(
            draft=ReportDraft(markdown="summary", cited_finding_ids=["f_1"]),
            findings=(),
        )
    )
    user_text = completions.calls[0]["messages"][1]["content"]
    assert "summary" in user_text
    assert "f_1" in user_text


async def test_generate_checklist_uses_text_model() -> None:
    client, completions = build(ChecklistSpec(name="tidy", expected_objects=["mug"]))
    spec = await client.generate_checklist("put the mug away")
    assert spec.name == "tidy"
    assert completions.calls[0]["model"] == "text-test"
    assert "put the mug away" in completions.calls[0]["messages"][1]["content"]


async def test_provider_errors_become_client_errors() -> None:
    client, _ = build(None, error=RuntimeError("connection refused"))

    with pytest.raises(ClientError) as caught:
        await client.extract_claims(ClaimsRequest(utterance=utterance()))

    assert caught.value.code == "model_call_failed"
    assert "connection refused" in str(caught.value)


def test_encode_image_uses_the_right_mime_type(tmp_path: Path) -> None:
    jpeg = tmp_path / "a.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff")
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG")

    assert encode_image(jpeg).startswith("data:image/jpeg;base64,")
    assert encode_image(png).startswith("data:image/png;base64,")
