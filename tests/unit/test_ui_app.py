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
        None,
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
    saved_text, dropdown, status = ui_app.on_save_spec(edited, "make_coffee.yaml", specs_dir=specs)

    assert "Saved" in status
    assert dropdown["value"] == "make_coffee.yaml"
    assert "stronger" in saved_text
    assert "stronger" in (specs / "make_coffee.yaml").read_text(encoding="utf-8")


def test_default_client_is_ollama() -> None:
    import gradio as gr

    demo = ui_app.build_ui()
    radios = [
        block
        for block in demo.blocks.values()
        if isinstance(block, gr.Radio) and block.label == "Client"
    ]
    assert radios
    assert radios[0].value == "ollama"


def test_initial_yaml_is_preloaded() -> None:
    import gradio as gr

    demo = ui_app.build_ui()
    boxes = [
        block
        for block in demo.blocks.values()
        if isinstance(block, gr.Textbox) and block.label == "Audit spec (editable YAML)"
    ]
    assert boxes
    assert "name: make_tea" in boxes[0].value


def test_generate_with_fake_client_warns(tmp_path: Path) -> None:
    specs = tmp_path / "specs"

    _text, _dropdown, status = ui_app.on_generate(
        "brew a cup of tea", "fake", None, specs_dir=specs
    )

    assert "fake" in status.lower()
    assert "coffee" in status.lower()
    assert (specs / "make_coffee.yaml").exists()


def test_save_uses_the_selected_filename_without_duplicates(tmp_path: Path) -> None:
    specs = tmp_path / "specs"
    specs.mkdir()
    tea = Path(__file__).parent.parent.parent / "specs" / "make_tea.yaml"
    edited = tea.read_text(encoding="utf-8").replace("name: make_tea", "name: make_tea_edited")

    saved_text, dropdown, status = ui_app.on_save_spec(edited, "make_tea.yaml", specs_dir=specs)

    assert "Saved" in status
    assert dropdown["value"] == "make_tea.yaml"
    assert (specs / "make_tea.yaml").exists()
    assert not (specs / "make_tea_edited.yaml").exists()
    assert "name: make_tea\n" in saved_text
    assert "make_tea_edited" not in saved_text
