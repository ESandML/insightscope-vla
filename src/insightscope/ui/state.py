"""UI behaviour that does not need Gradio.

Keeping the audio decision here means the silent-video rule can be tested directly,
and the Gradio layer stays a thin wiring file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from insightscope.telemetry.whisper import has_audio_stream


@dataclass(frozen=True, slots=True)
class AudioState:
    """What the speech controls should show for the current sources."""

    has_audio: bool
    listen_available: bool
    listen_value: bool
    show_upload: bool
    status: str


def audio_state(video: Path | None, external_audio: Path | None) -> AudioState:
    if video is None:
        return AudioState(
            has_audio=False,
            listen_available=False,
            listen_value=False,
            show_upload=False,
            status="Upload a video to begin.",
        )

    if has_audio_stream(video):
        return AudioState(
            has_audio=True,
            listen_available=True,
            listen_value=True,
            show_upload=False,
            status="Audio track detected. Listening to the video is available.",
        )

    if external_audio is not None:
        return AudioState(
            has_audio=False,
            listen_available=False,
            listen_value=False,
            show_upload=True,
            status=f"No audio track in the video. Using external audio: {external_audio.name}",
        )

    return AudioState(
        has_audio=False,
        listen_available=False,
        listen_value=False,
        show_upload=True,
        status=(
            "No audio track detected. Upload a voice recording, provide a transcript, "
            "or run against an audit spec."
        ),
    )
