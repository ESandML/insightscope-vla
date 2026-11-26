"""Speech-to-text: pure segment conversion, plus the lazy dependency boundary."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from insightscope.telemetry.whisper import (
    TranscriptionError,
    TranscriptionUnavailable,
    segments_to_utterances,
    transcribe,
)


def segment(start: float, end: float, text: str, logprob: float = -0.2) -> SimpleNamespace:
    return SimpleNamespace(start=start, end=end, text=text, avg_logprob=logprob)


def test_segments_become_time_anchored_utterances() -> None:
    utterances = segments_to_utterances(
        [segment(0.0, 1.5, " I closed the laptop "), segment(2.0, 3.0, "and the mug")]
    )

    assert [u.text for u in utterances] == ["I closed the laptop", "and the mug"]
    assert utterances[0].span.t_start_s == 0.0
    assert utterances[1].span.t_end_s == 3.0
    assert all(u.utterance_id.startswith("u_") for u in utterances)


def test_empty_segments_are_skipped() -> None:
    assert segments_to_utterances([segment(0.0, 1.0, "   ")]) == ()


def test_reversed_times_are_repaired() -> None:
    utterances = segments_to_utterances([segment(5.0, 4.0, "hello")])
    assert utterances[0].span.t_end_s > utterances[0].span.t_start_s


def test_segments_are_sorted() -> None:
    utterances = segments_to_utterances([segment(5.0, 6.0, "second"), segment(1.0, 2.0, "first")])
    assert [u.text for u in utterances] == ["first", "second"]


def test_confidence_is_clamped() -> None:
    utterances = segments_to_utterances(
        [segment(0.0, 1.0, "a", logprob=-4.0), segment(1.0, 2.0, "b", logprob=0.5)]
    )
    assert utterances[0].confidence == 0.0
    assert utterances[1].confidence == 1.0


def test_missing_dependency_is_reported_clearly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(TranscriptionUnavailable, match="asr extra"):
        transcribe(tmp_path / "clip.mp4")


def test_transcribe_wraps_the_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = types.ModuleType("faster_whisper")
    created: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, model_size: str, *, device: str, compute_type: str) -> None:
            created.update(
                {"model_size": model_size, "device": device, "compute_type": compute_type}
            )

        def transcribe(self, path: str, **kwargs: object) -> tuple[list, object]:
            created["path"] = path
            created["kwargs"] = kwargs
            return [segment(0.0, 1.0, " hello ")], SimpleNamespace(language="en")

    module.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)

    bundle = transcribe(tmp_path / "clip.mp4", model_size="tiny.en")

    assert bundle.mode == "asr"
    assert bundle.utterances[0].text == "hello"
    assert created["model_size"] == "tiny.en"
    assert created["compute_type"] == "int8"
    assert created["kwargs"] == {"vad_filter": True, "word_timestamps": True}  # type: ignore[index]


def test_no_speech_is_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = types.ModuleType("faster_whisper")

    class SilentModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def transcribe(self, path: str, **kwargs: object) -> tuple[list, object]:
            return [], SimpleNamespace()

    module.WhisperModel = SilentModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", module)

    with pytest.raises(TranscriptionError, match="no speech"):
        transcribe(tmp_path / "silent.mp4")
