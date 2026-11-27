"""UI run adapter: same pipeline, display-ready results."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from tests.support import write_test_video

from insightscope.clients.cassettes import Cassette, CassetteRecorder
from insightscope.clients.factory import ClientTriple
from insightscope.clients.fake import FakeTextClient, FakeVisionClient
from insightscope.contracts.extraction import ClaimItem
from insightscope.domain.checklist import load_checklist
from insightscope.domain.ontology import Attribute
from insightscope.inputs import plan_for
from insightscope.ui.service import UiRequest, generate_spec_text, run_ui_audit

CHECKLIST = Path(__file__).parent.parent / "fixtures" / "checklists" / "make_coffee.yaml"
TEXT = "I filled the kettle"


def clipboard(tmp_path: Path) -> Path:
    clip = write_test_video(tmp_path / "clip.avi", flash_at=None)
    return clip


def transcript(tmp_path: Path) -> Path:
    path = tmp_path / "t.json"
    path.write_text(
        json.dumps([{"t_start_s": 1.0, "t_end_s": 2.0, "text": TEXT}]),
        encoding="utf-8",
    )
    return path


def fake_triple() -> ClientTriple:
    text = FakeTextClient(
        claims={
            TEXT: [
                ClaimItem(
                    subject="kettle",
                    attribute=Attribute.PRESENCE,
                    value=True,
                    quote=TEXT,
                )
            ]
        }
    )
    return ClientTriple(text=text, vision=FakeVisionClient(), generator=text)


def request(tmp_path: Path, **overrides: object) -> UiRequest:
    base = UiRequest(
        clip=clipboard(tmp_path),
        plan=plan_for(transcript=True),
        transcript_path=transcript(tmp_path),
        artifacts_dir=tmp_path / "artifacts",
        db_path=tmp_path / "audits.db",
        specs_dir=tmp_path / "specs",
        client="fake",
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_open_ended_run_returns_display_values(tmp_path: Path) -> None:
    result = run_ui_audit(request(tmp_path), clients=fake_triple())
    assert result.ok
    assert result.status == "complete"
    assert "Audit report" in result.report_markdown
    assert result.keyframes
    assert all("·" in caption for _, caption in result.keyframes)

    payload = json.loads(result.assertions_json)
    assert payload["claims"][0]["subject_id"] == "kettle"
    assert len(result.history) == 1


def test_spec_run_splits_report_and_exposes_yaml(tmp_path: Path) -> None:
    spec = load_checklist(CHECKLIST)
    result = run_ui_audit(
        request(tmp_path, plan=plan_for(spec=True), transcript_path=None, spec=spec),
        clients=fake_triple(),
    )

    assert result.ok
    assert "make_coffee" in result.spec_yaml
    assert "### Process / Spec Compliance" in result.report_markdown
    assert "### Speech / Transcript Verification" in result.report_markdown


def test_generated_spec_is_written_to_the_run_directory(tmp_path: Path) -> None:
    spec = load_checklist(CHECKLIST)
    result = run_ui_audit(
        request(
            tmp_path,
            plan=plan_for(process=True),
            transcript_path=None,
            spec=spec,
            generated_spec=True,
        ),
        clients=fake_triple(),
    )

    assert result.ok
    generated = list((tmp_path / "artifacts").glob("*/generated_spec.yaml"))
    assert generated and "make_coffee" in generated[0].read_text(encoding="utf-8")
    assert (tmp_path / "specs" / "make_coffee.yaml").exists()


def test_run_can_be_replayed_from_a_cassette(tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "ui.cassette.json")
    fakes = fake_triple()
    recorder = ClientTriple(
        text=CassetteRecorder(fakes.text, cassette),
        vision=CassetteRecorder(fakes.vision, cassette),
        generator=CassetteRecorder(fakes.generator, cassette),
    )

    first = run_ui_audit(request(tmp_path), clients=recorder)
    cassette.save()

    second = run_ui_audit(
        request(tmp_path, client="cassette", cassette_path=cassette.path),
    )

    assert first.ok and second.ok
    assert second.status == first.status
    assert second.report_markdown == first.report_markdown


def test_generate_spec_text_returns_editable_yaml(tmp_path: Path) -> None:
    text = generate_spec_text("fill the kettle and pour water", client="fake")
    assert "make_coffee" in text
    assert "steps:" in text


def test_errors_are_returned_not_raised(tmp_path: Path) -> None:
    result = run_ui_audit(
        request(tmp_path, clip=tmp_path / "missing.avi"),
        clients=fake_triple(),
    )
    assert not result.ok
    assert result.error is not None


def test_ui_request_defaults_to_ollama() -> None:
    assert UiRequest(clip=Path("clip.mp4"), plan=plan_for()).client == "ollama"
