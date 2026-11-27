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
    specs = tmp_path / "specs"

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
        specs_dir=specs,
        artifacts_dir=tmp_path / "artifacts",
        db_path=tmp_path / "audits.db",
        progress=NoopProgress(),
    )

    status, keyframes, flagged, assertions, spec_text, report, history, dropdown = outputs
    assert "complete" in status
    assert keyframes
    # Missing-step findings have no frame to annotate.
    assert flagged == []
    findings = json.loads(assertions)["findings"]
    assert findings
    assert all(item["discrepancy"]["rule_id"].startswith("R-STEP-") for item in findings)
    assert "make_coffee" in spec_text
    assert (specs / "make_coffee.yaml").exists()
    assert dropdown["value"] == "make_coffee.yaml"
    assert "Findings" in report
    assert history


def test_generate_spec_callback_handles_empty_input() -> None:
    text, dropdown, status = ui_app.on_generate("   ", "fake", None)
    assert isinstance(text, dict)
    assert isinstance(dropdown, dict)
    assert "error" in status


def test_spec_upload_saves_into_specs_dir(tmp_path: Path) -> None:
    specs = tmp_path / "specs"

    text, dropdown, status = ui_app.on_spec_upload(str(CHECKLIST), specs_dir=specs)

    assert (specs / "make_coffee.yaml").exists()
    assert "make_coffee" in text
    assert "make_coffee.yaml" in dropdown["choices"]
    assert "Saved" in status


def test_generate_spec_saves_and_selects_it(tmp_path: Path) -> None:
    specs = tmp_path / "specs"

    text, dropdown, status = ui_app.on_generate(
        "fill the kettle, then pour water into the mug",
        "fake",
        None,
        specs_dir=specs,
    )

    assert (specs / "make_coffee.yaml").exists()
    assert dropdown["value"] == "make_coffee.yaml"
    assert "make_coffee" in text
    assert "saved" in status.lower()


def test_selecting_and_saving_a_spec_persists_edits(tmp_path: Path) -> None:
    specs = tmp_path / "specs"
    _text, _dropdown, _status = ui_app.on_spec_upload(str(CHECKLIST), specs_dir=specs)

    loaded, status = ui_app.on_select_spec("make_coffee.yaml", specs_dir=specs)
    assert "make_coffee" in loaded
    assert "Loaded" in status

    edited = loaded.replace("Brew a coffee", "Brew a stronger coffee")
    dropdown, status = ui_app.on_save_spec(edited, specs_dir=specs)

    assert "Saved" in status
    assert dropdown["value"] == "make_coffee.yaml"
    assert "stronger" in (specs / "make_coffee.yaml").read_text(encoding="utf-8")
