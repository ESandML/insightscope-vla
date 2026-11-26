"""Speech-to-text fallback when no transcript file is supplied.

``faster-whisper`` is an optional dependency (``--extra asr``) and is imported lazily,
so the core install and the test suite never need it. Segmentation is separated from
model loading: the conversion from whisper segments to ``Utterance`` objects is pure and
therefore testable without downloading weights.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from insightscope.domain.models import TimeSpan, Utterance
from insightscope.telemetry.transcript_source import TranscriptBundle, utterance_id


class TranscriptionUnavailable(RuntimeError):
    """faster-whisper is not installed."""


class TranscriptionError(RuntimeError):
    """The audio produced no usable speech segments."""


def has_audio_stream(video_path: str | Path) -> bool:
    """True when the container has at least one audio stream.

    Returns True when it cannot tell (PyAV missing, container unreadable): a caller
    should let transcription produce the specific error rather than claim silence.
    PyAV ships with faster-whisper, so when the ``asr`` extra is installed this is a
    real check.
    """
    try:
        import av
    except ImportError:
        return True

    try:
        with av.open(str(video_path)) as container:
            return any(stream.type == "audio" for stream in container.streams)
    except Exception:
        return True


def transcribe(
    audio_path: str | Path,
    *,
    model_size: str = "small.en",
    device: str = "auto",
    compute_type: str = "int8",
) -> TranscriptBundle:
    """Transcribe a clip and return time-anchored utterances."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptionUnavailable(
            "speech-to-text needs the asr extra: uv sync --extra asr"
        ) from exc

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _info = model.transcribe(
        str(audio_path),
        vad_filter=True,
        word_timestamps=True,
    )

    utterances = segments_to_utterances(segments)
    if not utterances:
        raise TranscriptionError(f"{audio_path}: no speech detected")
    return TranscriptBundle(utterances=utterances, mode="asr")


def segments_to_utterances(segments: Iterable[Any]) -> tuple[Utterance, ...]:
    """Convert whisper-like segments (anything with .start/.end/.text) to utterances.

    Pure, so it can be tested with a handful of stand-in objects instead of a model.
    """
    utterances: list[Utterance] = []
    for segment in segments:
        text = " ".join(str(getattr(segment, "text", "")).split())
        if not text:
            continue

        start = float(getattr(segment, "start", 0.0))
        end = float(getattr(segment, "end", start))
        if end <= start:
            end = start + 0.01

        utterances.append(
            Utterance(
                utterance_id=utterance_id(text, start, end),
                text=text,
                span=TimeSpan(t_start_s=start, t_end_s=end),
                confidence=_confidence(getattr(segment, "avg_logprob", None)),
            )
        )

    utterances.sort(key=lambda utterance: (utterance.span.t_start_s, utterance.span.t_end_s))
    return tuple(utterances)


def _confidence(avg_logprob: object) -> float:
    """Whisper reports mean log-probability; map it into 0..1 without pretending."""
    try:
        value = float(avg_logprob)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, 1.0 + value))
