"""Gradio app smoke tests: wiring and callbacks, no server launched."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("gradio")

from insightscope.ui import app as ui_app

CHECKLIST = Path(__file__).parent.parent / "fixtures" / "checklists" / "make_coffee.yaml"


class NoopProgress:
    def __call__(self, *args: object, **kwargs: object) -> None:
        return None


def test_build_ui_returns_blocks() -> None:
    demo = ui_app.build_ui()
    assert demo is not None
    assert len(demo.blocks) > 20


def test_video_change_explains_a_silent_clip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.support import write_test_video

    clip = write_test_video(tmp_path / "clip.avi", flash_at=None)
    monkeypatch.setattr("insightscope.ui.state.has_audio_stream", lambda _path: False)

    listen_update, upload_update, status = ui_app.on_sources(str(clip), None)

    assert listen_update["interactive"] is False
    assert upload_update["visible"] is True
    assert "No audio track" in status


def test_run_handler_produces_report_and_history(tmp_path: Path) -> None:
    from tests.support import write_test_video

    clip = write_test_video(tmp_path / "clip.avi", flash_at=None)

    outputs = ui_app.on_run(
        str(clip),
        False,
        None,
        "",
        "",
        str(CHECKLIST),
        "fake",
        None,
        False,
        progress=NoopProgress(),
    )

    status, keyframes, flagged, assertions, spec_text, report, history = outputs
    assert "complete" in status
    assert keyframes
    # Missing-step findings have no frame to annotate.
    assert flagged == []
    findings = json.loads(assertions)["findings"]
    assert findings
    assert all(item["discrepancy"]["rule_id"].startswith("R-STEP-") for item in findings)
    assert "make_coffee" in spec_text
    assert "Findings" in report
    assert history


def test_generate_spec_callback_handles_empty_input() -> None:
    text, status = ui_app.on_generate("   ", "fake", None)
    assert isinstance(text, dict)
    assert "error" in status
