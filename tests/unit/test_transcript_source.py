"""Transcript loading: timestamped JSON, and honest plain text."""

import json
from pathlib import Path

import pytest

from insightscope.telemetry.transcript_source import (
    TranscriptError,
    load_transcript,
)


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_json_segments_become_utterances(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "t.json",
        [
            {"t_start_s": 0.0, "t_end_s": 2.0, "text": "I closed the laptop"},
            {"t_start_s": 5.0, "t_end_s": 7.0, "text": "the mug is on the tray"},
        ],
    )
    bundle = load_transcript(path)

    assert bundle.mode == "json"
    assert [u.text for u in bundle.utterances] == [
        "I closed the laptop",
        "the mug is on the tray",
    ]
    assert bundle.utterances[1].span.t_start_s == 5.0


def test_segments_object_is_accepted(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "t.json",
        {"segments": [{"t_start_s": 1.0, "t_end_s": 2.0, "text": "hello"}]},
    )
    assert load_transcript(path).utterances[0].text == "hello"


def test_start_and_end_aliases_are_accepted(tmp_path: Path) -> None:
    path = write_json(tmp_path / "t.json", [{"start": 1.0, "end": 3.0, "text": "hi"}])
    utterance = load_transcript(path).utterances[0]
    assert (utterance.span.t_start_s, utterance.span.t_end_s) == (1.0, 3.0)


def test_segments_are_sorted_by_time(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / "t.json",
        [
            {"t_start_s": 9.0, "t_end_s": 10.0, "text": "second"},
            {"t_start_s": 1.0, "t_end_s": 2.0, "text": "first"},
        ],
    )
    assert [u.text for u in load_transcript(path).utterances] == ["first", "second"]


def test_utterance_ids_are_stable(tmp_path: Path) -> None:
    payload = [{"t_start_s": 1.0, "t_end_s": 2.0, "text": "same words"}]
    first = load_transcript(write_json(tmp_path / "a.json", payload))
    second = load_transcript(write_json(tmp_path / "b.json", payload))
    assert first.utterances[0].utterance_id == second.utterances[0].utterance_id


def test_missing_timestamp_is_an_error(tmp_path: Path) -> None:
    path = write_json(tmp_path / "t.json", [{"text": "no times here"}])
    with pytest.raises(TranscriptError, match="missing a timestamp"):
        load_transcript(path)


def test_reversed_span_is_an_error(tmp_path: Path) -> None:
    path = write_json(tmp_path / "t.json", [{"t_start_s": 5.0, "t_end_s": 1.0, "text": "x"}])
    with pytest.raises(TranscriptError, match="invalid time span"):
        load_transcript(path)


def test_empty_text_is_an_error(tmp_path: Path) -> None:
    path = write_json(tmp_path / "t.json", [{"t_start_s": 1.0, "t_end_s": 2.0, "text": "  "}])
    with pytest.raises(TranscriptError, match="no text"):
        load_transcript(path)


def test_invalid_json_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(TranscriptError, match="invalid JSON"):
        load_transcript(path)


def test_text_transcript_spans_the_clip(tmp_path: Path) -> None:
    path = tmp_path / "t.txt"
    path.write_text("I closed the laptop.\n", encoding="utf-8")

    bundle = load_transcript(path, duration_s=60.0)

    assert bundle.mode == "text"
    assert len(bundle.utterances) == 1
    assert bundle.utterances[0].span.t_start_s == 0.0
    assert bundle.utterances[0].span.t_end_s == 60.0


def test_text_transcript_without_duration_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "t.txt"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(TranscriptError, match="duration"):
        load_transcript(path)


def test_unknown_extension_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "t.md"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(TranscriptError, match="unsupported format"):
        load_transcript(path)


def test_missing_file_reports_the_path(tmp_path: Path) -> None:
    with pytest.raises(TranscriptError, match=r"nope\.json"):
        load_transcript(tmp_path / "nope.json")
