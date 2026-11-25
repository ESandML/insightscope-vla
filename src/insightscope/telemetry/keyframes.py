"""OpenCV keyframe selection: where the audit is allowed to look.

Three sources of candidate frames, in priority order:

1. **Transcript snaps** — the moments just before and after someone speaks, as a
   before/after pair for the vision model.
2. **Anchors** — t=0 and every ``anchor_every_s`` regardless of motion. Without these,
   a mug that never moves is invisible and every "you said it was there" claim looks
   unsupported.
3. **Motion** — frame differencing with a cooldown, so one action yields one frame
   instead of twenty near-identical ones.

Two passes keep memory flat: the first decodes small greyscale frames to score motion,
the second seeks back by frame index for the handful we actually keep.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from insightscope.config import KeyframeConfig
from insightscope.domain.models import KeyframeReason, KeyframeRef, TimeSpan, Utterance

_ANALYSIS_WIDTH = 160
_DEDUPE_WINDOW_S = 0.25
_JPEG_QUALITY = 85
_PRIORITY: dict[KeyframeReason, int] = {
    "snap_before": 3,
    "snap_after": 3,
    "anchor": 2,
    "motion": 1,
    "fallback": 0,
}


class TelemetryError(ValueError):
    """The clip is missing, unreadable, or yielded no frames."""


@dataclass(frozen=True, slots=True)
class _Sample:
    frame_index: int
    t_s: float
    score: float


@dataclass(frozen=True, slots=True)
class _Candidate:
    frame_index: int
    t_s: float
    reason: KeyframeReason
    score: float = 0.0


def video_duration(video_path: Path) -> float:
    """Seconds, or 0.0 when the container does not report a frame count."""
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise TelemetryError(f"{video_path}: cannot be opened")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS)) or 0.0
        count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0.0
        return count / fps if fps > 0 and count > 0 else 0.0
    finally:
        capture.release()


def select_keyframes(
    *,
    video_path: Path,
    out_dir: Path,
    config: KeyframeConfig,
    utterances: Sequence[Utterance] = (),
) -> tuple[KeyframeRef, ...]:
    """Pick, extract, and save keyframes. Returns refs sorted by time."""
    if not video_path.exists():
        raise TelemetryError(f"{video_path}: file not found")

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise TelemetryError(f"{video_path}: cannot be opened")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS)) or 25.0
        samples = _scan(capture, fps, config)
    finally:
        capture.release()

    if not samples:
        raise TelemetryError(f"{video_path}: no frames could be decoded")

    duration = samples[-1].t_s
    candidates = _choose(samples, utterances, config, duration)
    if not candidates:
        raise TelemetryError(f"{video_path}: no candidate frames survived selection")

    return _write(video_path, out_dir, candidates, fps, config)


def _scan(capture: Any, fps: float, config: KeyframeConfig) -> list[_Sample]:
    """Decode at ``analysis_fps`` and score motion between sampled frames."""
    step = max(1, round(fps / config.analysis_fps))
    samples: list[_Sample] = []
    previous: np.ndarray | None = None
    index = 0

    while True:
        position_ms = float(capture.get(cv2.CAP_PROP_POS_MSEC))
        ok, frame = capture.read()
        if not ok:
            break

        if index % step == 0:
            t_s = position_ms / 1000.0 if position_ms > 0 else index / fps
            height, width = frame.shape[:2]
            small = cv2.resize(
                frame,
                (_ANALYSIS_WIDTH, max(1, int(height * _ANALYSIS_WIDTH / max(1, width)))),
            )
            grey = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            score = 0.0 if previous is None else float(cv2.absdiff(grey, previous).mean())
            previous = grey
            samples.append(_Sample(frame_index=index, t_s=t_s, score=score))

        index += 1

    return samples


def _choose(
    samples: Sequence[_Sample],
    utterances: Sequence[Utterance],
    config: KeyframeConfig,
    duration: float,
) -> list[_Candidate]:
    candidates: dict[int, _Candidate] = {}

    last_motion = float("-inf")
    for sample in samples:
        if sample.score < config.motion_threshold:
            continue
        if sample.t_s - last_motion < config.cooldown_s:
            continue
        _add(candidates, _Candidate(sample.frame_index, sample.t_s, "motion", sample.score))
        last_motion = sample.t_s

    anchors = [0.0]
    target = config.anchor_every_s
    while target <= duration:
        anchors.append(target)
        target += config.anchor_every_s
    for anchor in anchors:
        nearest = _nearest(samples, anchor)
        _add(candidates, _Candidate(nearest.frame_index, nearest.t_s, "anchor"))

    for utterance in utterances:
        before = max(0.0, utterance.span.t_start_s - config.snap_before_s)
        after = utterance.span.t_end_s + config.snap_after_s
        snaps: tuple[tuple[float, KeyframeReason], ...] = (
            (before, "snap_before"),
            (after, "snap_after"),
        )
        for moment, reason in snaps:
            nearest = _nearest(samples, moment)
            _add(candidates, _Candidate(nearest.frame_index, nearest.t_s, reason))

    ordered = sorted(
        candidates.values(),
        key=lambda candidate: (
            -_PRIORITY[candidate.reason],
            -candidate.score,
            candidate.t_s,
        ),
    )
    kept = ordered[: config.max_keyframes]
    kept.sort(key=lambda candidate: (candidate.t_s, candidate.frame_index))
    return kept


def _nearest(samples: Sequence[_Sample], target_s: float) -> _Sample:
    return min(samples, key=lambda sample: (abs(sample.t_s - target_s), sample.frame_index))


def _add(candidates: dict[int, _Candidate], candidate: _Candidate) -> None:
    """Insert unless a frame within the dedupe window wins on priority, then score."""
    for key, existing in list(candidates.items()):
        if abs(existing.t_s - candidate.t_s) > _DEDUPE_WINDOW_S:
            continue
        if _PRIORITY[candidate.reason] > _PRIORITY[existing.reason]:
            del candidates[key]
            continue
        if (
            _PRIORITY[candidate.reason] == _PRIORITY[existing.reason]
            and candidate.score > existing.score
        ):
            del candidates[key]
            continue
        return
    candidates[candidate.frame_index] = candidate


def _write(
    video_path: Path,
    out_dir: Path,
    candidates: Sequence[_Candidate],
    fps: float,
    config: KeyframeConfig,
) -> tuple[KeyframeRef, ...]:
    out_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise TelemetryError(f"{video_path}: cannot be reopened for extraction")

    refs: list[KeyframeRef] = []
    try:
        for sequence, candidate in enumerate(candidates):
            capture.set(cv2.CAP_PROP_POS_FRAMES, candidate.frame_index)
            ok, frame = capture.read()
            if not ok:
                continue

            frame = _resize(frame, config.max_frame_side)
            encoded_ok, buffer = cv2.imencode(
                ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY]
            )
            if not encoded_ok:
                continue

            payload = buffer.tobytes()
            digest = hashlib.sha256(payload + f"{candidate.t_s:.3f}".encode()).hexdigest()
            keyframe_id = f"kf_{sequence:03d}_{digest[:8]}"
            path = out_dir / f"{keyframe_id}.jpg"
            path.write_bytes(payload)

            height, width = frame.shape[:2]
            refs.append(
                KeyframeRef(
                    keyframe_id=keyframe_id,
                    uri=str(path),
                    sha256=digest,
                    span=TimeSpan(
                        t_start_s=candidate.t_s,
                        t_end_s=candidate.t_s + (1.0 / fps if fps > 0 else 0.0),
                    ),
                    reason=candidate.reason,
                    width=width,
                    height=height,
                )
            )
    finally:
        capture.release()

    if not refs:
        raise TelemetryError(f"{video_path}: no keyframes could be written")
    return tuple(refs)


def _resize(frame: np.ndarray, max_side: int) -> np.ndarray:
    height, width = frame.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return frame
    scale = max_side / longest
    return cv2.resize(
        frame,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_AREA,
    )
