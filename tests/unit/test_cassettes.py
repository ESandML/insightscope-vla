"""Cassettes: record real responses once, replay them anywhere."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support import keyframe

from insightscope.clients.base import ClaimsRequest, VisionRequest
from insightscope.clients.cassettes import (
    Cassette,
    CassetteFormatError,
    CassetteMiss,
    CassettePlayer,
    CassetteRecorder,
    entry_key,
    load_cassette,
)
from insightscope.clients.fake import FakeTextClient, FakeVisionClient
from insightscope.contracts.extraction import ClaimBatch, ClaimItem, KeyframeAnalysis
from insightscope.domain.models import TimeSpan, Utterance
from insightscope.domain.ontology import Attribute


def utterance(text: str = "I closed the laptop") -> Utterance:
    return Utterance(
        utterance_id="u_0001",
        text=text,
        span=TimeSpan(t_start_s=1.0, t_end_s=2.0),
    )


def recording_client() -> FakeTextClient:
    return FakeTextClient(
        claims={
            "I closed the laptop": [
                ClaimItem(
                    subject="laptop",
                    attribute=Attribute.OPEN_CLOSED,
                    value="closed",
                    quote="I closed the laptop",
                )
            ]
        }
    )


async def test_record_then_replay_returns_the_same_objects(tmp_path: Path) -> None:
    path = tmp_path / "desk.cassette.json"
    cassette = Cassette(path)
    text = CassetteRecorder(recording_client(), cassette)
    vision = CassetteRecorder(
        FakeVisionClient(
            analyses={
                "kf_0001": KeyframeAnalysis(
                    keyframe_id="kf_0001",
                    verified=[
                        {
                            "subject": "laptop",
                            "attribute": "open_closed_state",
                            "value": "closed",
                            "confidence": 0.9,
                        }
                    ],
                )
            }
        ),
        cassette,
    )

    request = ClaimsRequest(utterance=utterance())
    batch = await text.extract_claims(request)
    analysis = await vision.analyse(VisionRequest(keyframe=keyframe("kf_0001", start=1.0, end=2.0)))
    cassette.save()

    player = CassettePlayer(load_cassette(path))
    assert await player.extract_claims(request) == batch
    assert (
        await player.analyse(VisionRequest(keyframe=keyframe("kf_0001", start=1.0, end=2.0)))
        == analysis
    )


async def test_cassette_keys_ignore_file_paths(tmp_path: Path) -> None:
    first = keyframe("kf_0001", start=1.0, end=2.0).model_copy(
        update={"uri": str(tmp_path / "a" / "kf.jpg")}
    )
    second = first.model_copy(update={"uri": str(tmp_path / "b" / "elsewhere.jpg")})

    assert entry_key("analyse", VisionRequest(keyframe=first)) == entry_key(
        "analyse", VisionRequest(keyframe=second)
    )


async def test_missing_entry_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.cassette.json"
    Cassette(path).save()
    player = CassettePlayer(load_cassette(path))

    with pytest.raises(CassetteMiss, match="extract_claims"):
        await player.extract_claims(ClaimsRequest(utterance=utterance("something else")))


async def test_checklist_generation_round_trips(tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "c.json")
    recorder = CassetteRecorder(FakeTextClient(), cassette)
    spec = await recorder.generate_checklist("close the laptop")
    cassette.save()

    player = CassettePlayer(load_cassette(tmp_path / "c.json"))
    assert await player.generate_checklist("close the laptop") == spec


def test_bad_cassette_version_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"version": 99, "entries": {}}', encoding="utf-8")
    with pytest.raises(CassetteFormatError, match="version"):
        load_cassette(path)


def test_missing_cassette_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CassetteFormatError, match="not found"):
        load_cassette(tmp_path / "nope.json")


async def test_response_types_survive_serialisation(tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "c.json")
    recorder = CassetteRecorder(recording_client(), cassette)
    await recorder.extract_claims(ClaimsRequest(utterance=utterance()))
    cassette.save()

    player = CassettePlayer(load_cassette(tmp_path / "c.json"))
    batch = await player.extract_claims(ClaimsRequest(utterance=utterance()))
    assert isinstance(batch, ClaimBatch)
    assert batch.claims[0].value == "closed"
