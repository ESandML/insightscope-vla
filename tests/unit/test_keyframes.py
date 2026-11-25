"""Keyframe selection: anchors, motion cooldown, snapping, cap, determinism."""

from pathlib import Path

import cv2
import pytest
from tests.support import write_test_video

from insightscope.config import KeyframeConfig
from insightscope.domain.models import TimeSpan, Utterance
from insightscope.telemetry.keyframes import (
    TelemetryError,
    select_keyframes,
    video_duration,
)


def utterance(start: float = 5.0, end: float = 6.0) -> Utterance:
    return Utterance(
        utterance_id="u_0001",
        text="I closed the laptop",
        span=TimeSpan(t_start_s=start, t_end_s=end),
    )


def select(clip: Path, out: Path, **kwargs: object):
    config = kwargs.pop("config", KeyframeConfig())
    utterances = kwargs.pop("utterances", ())
    return select_keyframes(
        video_path=clip,
        out_dir=out,
        config=config,  # type: ignore[arg-type]
        utterances=utterances,  # type: ignore[arg-type]
    )


def test_video_duration_is_reported(tmp_path: Path) -> None:
    clip = write_test_video(tmp_path / "clip.avi", seconds=12.0)
    assert video_duration(clip) == pytest.approx(12.0, abs=0.2)


def test_anchors_are_selected_without_any_motion(tmp_path: Path) -> None:
    clip = write_test_video(tmp_path / "static.avi", flash_at=None)
    refs = select(clip, tmp_path / "out")

    times = [ref.span.t_start_s for ref in refs]
    assert any(abs(t - 0.0) <= 0.2 for t in times)
    assert any(abs(t - 10.0) <= 0.2 for t in times)
    assert {ref.reason for ref in refs} == {"anchor"}


def test_motion_is_selected_once_per_cooldown(tmp_path: Path) -> None:
    clip = write_test_video(tmp_path / "flash.avi", flash_at=3.0)
    refs = select(clip, tmp_path / "out")

    motion = [ref for ref in refs if ref.reason == "motion"]
    assert len(motion) == 1
    assert 2.8 <= motion[0].span.t_start_s <= 3.4


def test_transcript_snapping_adds_before_and_after(tmp_path: Path) -> None:
    clip = write_test_video(tmp_path / "static.avi", flash_at=None)
    refs = select(clip, tmp_path / "out", utterances=(utterance(5.0, 6.0),))

    reasons = {ref.reason for ref in refs}
    assert "snap_before" in reasons
    assert "snap_after" in reasons

    before = next(ref for ref in refs if ref.reason == "snap_before")
    after = next(ref for ref in refs if ref.reason == "snap_after")
    assert 4.0 <= before.span.t_start_s <= 5.0
    assert 6.5 <= after.span.t_start_s <= 7.5


def test_cap_keeps_the_highest_priority_frames(tmp_path: Path) -> None:
    clip = write_test_video(tmp_path / "clip.avi", flash_at=3.0)
    refs = select(
        clip,
        tmp_path / "out",
        config=KeyframeConfig(max_keyframes=2),
        utterances=(utterance(5.0, 6.0),),
    )
    assert len(refs) == 2
    assert all(ref.reason.startswith("snap") for ref in refs)


def test_images_are_written_and_resized(tmp_path: Path) -> None:
    clip = write_test_video(tmp_path / "clip.avi")
    refs = select(clip, tmp_path / "out", config=KeyframeConfig(max_frame_side=64))

    for ref in refs:
        assert Path(ref.uri).exists()
        image = cv2.imread(ref.uri)
        assert image is not None
        assert max(image.shape[:2]) <= 64


def test_keyframes_are_sorted_by_time(tmp_path: Path) -> None:
    clip = write_test_video(tmp_path / "clip.avi")
    refs = select(clip, tmp_path / "out", utterances=(utterance(),))
    times = [ref.span.t_start_s for ref in refs]
    assert times == sorted(times)


def test_selection_is_deterministic(tmp_path: Path) -> None:
    clip = write_test_video(tmp_path / "clip.avi")
    first = select(clip, tmp_path / "a")
    second = select(clip, tmp_path / "b")

    assert [ref.keyframe_id for ref in first] == [ref.keyframe_id for ref in second]
    assert [ref.sha256 for ref in first] == [ref.sha256 for ref in second]


def test_missing_clip_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(TelemetryError, match="not found"):
        select(tmp_path / "nope.mp4", tmp_path / "out")


def test_unreadable_clip_is_an_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.avi"
    broken.write_bytes(b"not a video")
    with pytest.raises(TelemetryError):
        select(broken, tmp_path / "out")
