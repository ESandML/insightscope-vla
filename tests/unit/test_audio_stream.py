"""Audio-stream probing, including the honest fallback when it cannot tell."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from insightscope.telemetry.whisper import has_audio_stream


def install_av(monkeypatch: pytest.MonkeyPatch, stream_types: list[str]) -> None:
    module = types.ModuleType("av")

    class Container:
        def __init__(self) -> None:
            self.streams = [SimpleNamespace(type=kind) for kind in stream_types]

        def __enter__(self) -> Container:
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    module.open = lambda path: Container()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "av", module)


def test_detects_an_audio_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    install_av(monkeypatch, ["video", "audio"])
    assert has_audio_stream(Path("clip.mp4")) is True


def test_reports_a_silent_video(monkeypatch: pytest.MonkeyPatch) -> None:
    install_av(monkeypatch, ["video"])
    assert has_audio_stream(Path("clip.mp4")) is False


def test_missing_av_is_treated_as_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "av", None)
    assert has_audio_stream(Path("clip.mp4")) is True


def test_unreadable_container_is_treated_as_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("av")

    def boom(path: str) -> object:
        raise RuntimeError("cannot probe")

    module.open = boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "av", module)

    assert has_audio_stream(Path("clip.mp4")) is True
