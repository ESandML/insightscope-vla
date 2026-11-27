"""Gradio app smoke tests: wiring, state transitions, and spec saving."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("gradio")

import gradio as gr

from insightscope.ui import app as ui_app
from insightscope.ui.specs import NEW_SPEC, save_enabled, spec_names

CHECKLIST = Path(__file__).parent.parent / "fixtures" / "checklists" / "make_coffee.yaml"
REPO_SPECS = Path(__file__).parent.parent.parent / "specs"


class NoopProgress:
    def __call__(self, *args: object, **kwargs: object) -> None:
        return None


def copy_tea(tmp_path: Path) -> Path:
    specs = tmp_path / "specs"
    specs.mkdir(exist_ok=True)
    (specs / "make_tea.yaml").write_text(
        (REPO_SPECS / "make_tea.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return specs


def block(demo: gr.Blocks, kind: type, label: str) -> object:
    found = [
        item
        for item in demo.blocks.values()
        if isinstance(item, kind)
        and label in {getattr(item, "label", None), getattr(item, "value", None)}
    ]
    assert found, f"no {kind.__name__} labelled {label!r}"
    return found[0]


def test_build_ui_returns_blocks() -> None:
    demo = ui_app.build_ui()
    assert demo is not None
    assert len(demo.blocks) > 20


def test_default_client_is_ollama() -> None:
    demo = ui_app.build_ui()
    assert block(demo, gr.Radio, "Client").value == "ollama"


def test_initial_yaml_is_preloaded_and_save_is_disabled() -> None:
    demo = ui_app.build_ui()
    assert "name: make_tea" in block(demo, gr.Textbox, "Audit spec (editable YAML)").value
    assert block(demo, gr.Button, "Save Spec").interactive is False
    assert block(demo, gr.Button, "Generate Spec").interactive is False


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


def test_existing_spec_loads_and_requires_a_change_to_save(tmp_path: Path) -> None:
    specs = copy_tea(tmp_path)

    outputs = ui_app.on_choice("make_tea.yaml", "", specs_dir=specs)
    text, _choice, filename, baseline, generate, save, validation, status = outputs

    assert text["value"].startswith("name: make_tea")
    assert filename["visible"] is False
    assert generate["interactive"] is False
    assert save["interactive"] is False
    assert validation == ""
    assert "Loaded" in status
    assert baseline == text["value"]

    _validation, save = ui_app.on_spec_text(text["value"] + "\n", "make_tea.yaml", baseline, "")
    assert save["interactive"] is False  # whitespace only

    edited = text["value"].replace(
        "Brew a cup of tea at the kitchen counter.", "Brew a strong cup of tea."
    )
    validation, save = ui_app.on_spec_text(edited, "make_tea.yaml", baseline, "")
    assert save["interactive"] is True
    assert validation == ""


def test_invalid_yaml_keeps_save_disabled_and_explains_why(tmp_path: Path) -> None:
    specs = copy_tea(tmp_path)
    outputs = ui_app.on_choice("make_tea.yaml", "", specs_dir=specs)
    baseline = outputs[3]

    validation, save = ui_app.on_spec_text(
        "name: make_tea\nsteps: [unclosed", "make_tea.yaml", baseline, ""
    )

    assert save["interactive"] is False
    assert "Invalid" in validation


def test_generate_regenerates_the_selected_spec_without_writing(
    tmp_path: Path,
) -> None:
    specs = copy_tea(tmp_path)
    before = (specs / "make_tea.yaml").read_text(encoding="utf-8")

    loaded = ui_app.on_choice("make_tea.yaml", "brew a pot of tea", specs_dir=specs)
    baseline = loaded[3]
    assert loaded[4]["interactive"] is True  # Generate enabled by the description
    assert loaded[5]["interactive"] is False  # Save still needs a change

    outputs = ui_app.on_generate(
        "brew a pot of tea", "fake", None, "make_tea.yaml", "", baseline, specs_dir=specs
    )
    text, _choice, _filename, new_baseline, generate, save, validation, status = outputs

    assert "Regenerated" in status
    assert "name: make_coffee" in text["value"]  # fake client fixture
    assert new_baseline == baseline  # saved baseline is unchanged
    assert generate["interactive"] is True
    assert save["interactive"] is True
    assert validation == ""
    assert save_enabled("make_tea.yaml", text["value"], baseline, "")

    # Nothing was written: the user reviews and saves explicitly.
    assert (specs / "make_tea.yaml").read_text(encoding="utf-8") == before
    assert spec_names(specs) == ["make_tea.yaml"]


def test_generate_needs_a_process_description(tmp_path: Path) -> None:
    specs = copy_tea(tmp_path)
    loaded = ui_app.on_choice("make_tea.yaml", "", specs_dir=specs)

    outputs = ui_app.on_generate(
        "   ", "fake", None, "make_tea.yaml", "", loaded[3], specs_dir=specs
    )

    assert outputs[4]["interactive"] is False
    assert "process description" in outputs[7]


def test_new_spec_clears_editor_and_requires_name_and_process(tmp_path: Path) -> None:
    specs = copy_tea(tmp_path)

    outputs = ui_app.on_choice(NEW_SPEC, "", specs_dir=specs)
    text, _choice, filename, baseline, generate, save, validation, status = outputs

    assert text["value"] == ""
    assert filename["visible"] is True
    assert baseline == ""
    assert generate["interactive"] is False
    assert save["interactive"] is False
    assert validation == ""
    assert "New spec" in status

    generate_update, _save = ui_app.on_new_filename("brew_tea.yaml", NEW_SPEC, "", "", "")
    assert generate_update["interactive"] is False

    generate_update, _save = ui_app.on_new_filename(
        "brew_tea.yaml", NEW_SPEC, "brew a pot of tea", "", ""
    )
    assert generate_update["interactive"] is True

    _validation, save = ui_app.on_spec_text("", NEW_SPEC, "", "brew_tea.yaml")
    assert save["interactive"] is False


def test_duplicate_filename_is_rejected_without_overwriting(tmp_path: Path) -> None:
    specs = copy_tea(tmp_path)
    before = (specs / "make_tea.yaml").read_text(encoding="utf-8")

    outputs = ui_app.on_generate(
        "brew tea", "fake", None, NEW_SPEC, "make_tea.yaml", "", specs_dir=specs
    )

    assert "already exists" in outputs[7]
    assert (specs / "make_tea.yaml").read_text(encoding="utf-8") == before


def test_duplicate_filename_is_rejected_on_save(tmp_path: Path) -> None:
    specs = copy_tea(tmp_path)
    text = (specs / "make_tea.yaml").read_text(encoding="utf-8")

    outputs = ui_app.on_save(text, NEW_SPEC, "", "make_tea.yaml", specs_dir=specs)

    assert "already exists" in outputs[7]


def test_existing_save_preserves_the_edited_name(tmp_path: Path) -> None:
    specs = copy_tea(tmp_path)
    text = (
        (specs / "make_tea.yaml")
        .read_text(encoding="utf-8")
        .replace("name: make_tea", "name: custom_tea")
    )

    outputs = ui_app.on_save(text, "make_tea.yaml", text, "", specs_dir=specs)

    assert outputs[5]["interactive"] is False
    assert "Saved" in outputs[7]
    assert spec_names(specs) == ["make_tea.yaml"]
    assert "name: custom_tea" in (specs / "make_tea.yaml").read_text(encoding="utf-8")


def test_upload_saves_and_rejects_duplicates(tmp_path: Path) -> None:
    specs = tmp_path / "specs"

    outputs = ui_app.on_spec_upload(str(CHECKLIST), "", specs_dir=specs)
    assert (specs / "make_coffee.yaml").exists()
    assert outputs[1]["value"] == "make_coffee.yaml"
    assert outputs[2]["visible"] is False
    assert "Saved" in outputs[7]

    duplicate = ui_app.on_spec_upload(str(CHECKLIST), "", specs_dir=specs)
    assert "already exists" in duplicate[7]


def test_generate_with_fake_client_warns(tmp_path: Path) -> None:
    specs = tmp_path / "specs"

    outputs = ui_app.on_generate(
        "brew a cup of tea", "fake", None, NEW_SPEC, "brew_tea.yaml", "", specs_dir=specs
    )

    assert "fake" in outputs[7].lower()
    assert "coffee" in outputs[7].lower()
    assert (specs / "brew_tea.yaml").exists()
    assert outputs[1]["value"] == "brew_tea.yaml"
    assert outputs[2]["visible"] is False


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
        NEW_SPEC,
        "",
        "fake",
        None,
        False,
        "",
        specs_dir=specs,
        artifacts_dir=tmp_path / "artifacts",
        db_path=tmp_path / "audits.db",
        progress=NoopProgress(),
    )

    assert len(outputs) == 13
    status, keyframes, flagged, assertions, spec_text, report, history, dropdown = outputs[:8]
    assert "complete" in status
    assert keyframes
    assert flagged == []
    findings = json.loads(assertions)["findings"]
    assert findings
    assert all(item["discrepancy"]["rule_id"].startswith("R-STEP-") for item in findings)
    assert "make_coffee" in spec_text
    assert (specs / "make_coffee.yaml").exists()
    assert dropdown["value"] == "make_coffee.yaml"
    assert "Findings" in report
    assert history
    assert outputs[11]["interactive"] is False  # save disabled after run
