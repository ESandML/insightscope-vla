"""UI audio-state transitions, tested without Gradio."""

from pathlib import Path

import pytest

from insightscope.ui import state as ui_state


@pytest.fixture
def silent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui_state, "has_audio_stream", lambda _path: False)


@pytest.fixture
def audible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ui_state, "has_audio_stream", lambda _path: True)


def test_no_video_disables_everything() -> None:
    state = ui_state.audio_state(None, None)
    assert state.listen_available is False
    assert state.show_upload is False
    assert "Upload a video" in state.status


def test_audible_video_enables_listen_and_hides_upload(audible: None) -> None:
    state = ui_state.audio_state(Path("clip.mp4"), None)
    assert state.has_audio is True
    assert state.listen_available is True
    assert state.listen_value is True
    assert state.show_upload is False


def test_silent_video_disables_listen_and_reveals_upload(silent: None) -> None:
    state = ui_state.audio_state(Path("clip.mp4"), None)
    assert state.has_audio is False
    assert state.listen_available is False
    assert state.listen_value is False
    assert state.show_upload is True
    assert "No audio track" in state.status


def test_silent_video_with_external_audio_names_the_file(silent: None) -> None:
    state = ui_state.audio_state(Path("clip.mp4"), Path("voice.wav"))
    assert state.show_upload is True
    assert state.listen_available is False
    assert "voice.wav" in state.status
