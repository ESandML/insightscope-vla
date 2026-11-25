"""Transcript loading: timestamped JSON, or plain text with the truth admitted.

Two formats, one return type. The important distinction is that a ``.json`` transcript
carries times, so claims can be aligned to keyframes; a ``.txt`` does not, so it becomes
a single utterance spanning the whole clip and is labelled ``text`` mode. Downstream
that becomes a visible "alignment is degraded" note, not a silent guess.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from insightscope.domain.models import TimeSpan, TranscriptionMode, Utterance

_START_KEYS = ("t_start_s", "start_s", "start")
_END_KEYS = ("t_end_s", "end_s", "end")


class TranscriptError(ValueError):
    """A transcript file is missing, malformed, or has no usable timestamps."""


@dataclass(frozen=True, slots=True)
class TranscriptBundle:
    utterances: tuple[Utterance, ...]
    mode: TranscriptionMode


def load_transcript(path: str | Path, *, duration_s: float | None = None) -> TranscriptBundle:
    """Load ``path`` as utterances. ``duration_s`` is required for ``.txt``."""
    source = Path(path)
    if not source.exists():
        raise TranscriptError(f"{source}: file not found")

    suffix = source.suffix.lower()
    if suffix == ".json":
        return TranscriptBundle(_load_json(source), "json")
    if suffix == ".txt":
        return TranscriptBundle(_load_text(source, duration_s), "text")
    raise TranscriptError(f"{source}: unsupported format {suffix or '(none)'!r}; use .json or .txt")


def utterance_id(text: str, start_s: float, end_s: float) -> str:
    """Stable across reloads, so evidence references survive a re-run."""
    digest = hashlib.sha256(f"{text}|{start_s:.3f}|{end_s:.3f}".encode()).hexdigest()
    return f"u_{digest[:8]}"


def _load_json(path: Path) -> tuple[Utterance, ...]:
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TranscriptError(f"{path}: invalid JSON: {exc}") from exc

    segments = raw.get("segments") if isinstance(raw, dict) else raw
    if not isinstance(segments, list):
        raise TranscriptError(
            f"{path}: expected a list of segments or an object with a 'segments' list"
        )
    if not segments:
        raise TranscriptError(f"{path}: transcript has no segments")

    utterances: list[Utterance] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise TranscriptError(f"{path}: segment {index} is not an object")

        text = str(segment.get("text", "")).strip()
        if not text:
            raise TranscriptError(f"{path}: segment {index} has no text")

        start = _number(path, segment, _START_KEYS, index)
        end = _number(path, segment, _END_KEYS, index)
        try:
            span = TimeSpan(t_start_s=start, t_end_s=end)
        except ValidationError as exc:
            raise TranscriptError(f"{path}: segment {index} has an invalid time span") from exc

        speaker = segment.get("speaker")
        utterances.append(
            Utterance(
                utterance_id=utterance_id(text, start, end),
                text=text,
                span=span,
                speaker=str(speaker) if speaker else None,
            )
        )

    utterances.sort(key=lambda u: (u.span.t_start_s, u.span.t_end_s))
    return tuple(utterances)


def _number(path: Path, segment: dict[str, Any], keys: tuple[str, ...], index: int) -> float:
    for key in keys:
        if key in segment:
            try:
                value = float(segment[key])
            except (TypeError, ValueError) as exc:
                raise TranscriptError(f"{path}: segment {index} has a non-numeric {key!r}") from exc
            if value < 0:
                raise TranscriptError(f"{path}: segment {index} has a negative time")
            return value
    raise TranscriptError(
        f"{path}: segment {index} is missing a timestamp (expected one of {keys})"
    )


def _load_text(path: Path, duration_s: float | None) -> tuple[Utterance, ...]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise TranscriptError(f"{path}: transcript is empty")
    if duration_s is None or duration_s <= 0:
        raise TranscriptError(
            f"{path}: a .txt transcript has no timestamps, so the clip duration is "
            "needed to place it on the timeline"
        )
    span = TimeSpan(t_start_s=0.0, t_end_s=duration_s)
    return (
        Utterance(
            utterance_id=utterance_id(text, 0.0, duration_s),
            text=text,
            span=span,
        ),
    )
