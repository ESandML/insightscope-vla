"""CLI behaviour: exit codes, printed summaries, and the files left behind."""

import importlib.util
import json
from pathlib import Path

import pytest
from tests.support import write_test_video

from insightscope.actions.db import history
from insightscope.cli import main
from insightscope.domain.models import TimeSpan, Utterance
from insightscope.telemetry.transcript_source import TranscriptBundle

CHECKLIST = Path(__file__).parent.parent / "fixtures" / "checklists" / "make_coffee.yaml"


def transcript_json(path: Path, text: str = "I closed the laptop") -> Path:
    path.write_text(
        json.dumps([{"t_start_s": 5.0, "t_end_s": 6.0, "text": text}]),
        encoding="utf-8",
    )
    return path


def test_keyframes_command_lists_selection(tmp_path: Path, capsys: object) -> None:
    clip = write_test_video(tmp_path / "clip.avi")
    out = tmp_path / "frames"

    code = main(["keyframes", str(clip), "--out", str(out)])

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert "selected" in captured.out
    assert "anchor" in captured.out
    assert list(out.glob("*.jpg"))


def test_keyframes_command_snaps_to_the_transcript(tmp_path: Path, capsys: object) -> None:
    clip = write_test_video(tmp_path / "clip.avi", flash_at=None)
    transcript = transcript_json(tmp_path / "t.json")

    code = main(
        ["keyframes", str(clip), "--out", str(tmp_path / "frames"), "--transcript", str(transcript)]
    )

    assert code == 0
    assert "snap_before" in capsys.readouterr().out  # type: ignore[attr-defined]


def test_audit_writes_report_and_log(tmp_path: Path, capsys: object) -> None:
    clip = write_test_video(tmp_path / "clip.avi")
    transcript = transcript_json(tmp_path / "t.json")
    artifacts = tmp_path / "artifacts"
    db = tmp_path / "audits.db"

    code = main(
        [
            "audit",
            str(clip),
            "--transcript",
            str(transcript),
            "--artifacts-dir",
            str(artifacts),
            "--db",
            str(db),
        ]
    )

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert "status:    complete" in captured.out
    assert "keyframes:" in captured.out
    assert "findings:  0" in captured.out

    reports = list(artifacts.glob("*/report.md"))
    assert len(reports) == 1
    report_text = reports[0].read_text(encoding="utf-8")
    assert "Audit report" in report_text
    assert "No conflicts were found" in report_text

    rows = history(db)
    assert len(rows) == 1
    assert rows[0]["status"] == "complete"


def test_audit_rerun_reuses_the_same_run_directory(tmp_path: Path) -> None:
    clip = write_test_video(tmp_path / "clip.avi")
    transcript = transcript_json(tmp_path / "t.json")
    artifacts = tmp_path / "artifacts"
    args = [
        "audit",
        str(clip),
        "--transcript",
        str(transcript),
        "--artifacts-dir",
        str(artifacts),
        "--db",
        str(tmp_path / "audits.db"),
    ]

    assert main(args) == 0
    assert main(args) == 0

    assert len(list(artifacts.iterdir())) == 1


def test_txt_transcript_is_reported_as_degraded(tmp_path: Path) -> None:
    clip = write_test_video(tmp_path / "clip.avi")
    transcript = tmp_path / "t.txt"
    transcript.write_text("I closed the laptop", encoding="utf-8")
    artifacts = tmp_path / "artifacts"

    code = main(
        [
            "audit",
            str(clip),
            "--transcript",
            str(transcript),
            "--artifacts-dir",
            str(artifacts),
            "--db",
            str(tmp_path / "audits.db"),
        ]
    )

    assert code == 0
    report = next(artifacts.glob("*/report.md")).read_text(encoding="utf-8")
    assert "no timestamps" in report
    assert "Evidence notes" in report


def test_spec_mode_enables_step_rules(tmp_path: Path, capsys: object) -> None:
    clip = write_test_video(tmp_path / "clip.avi")
    transcript = transcript_json(tmp_path / "t.json")
    artifacts = tmp_path / "artifacts"

    code = main(
        [
            "audit",
            str(clip),
            "--transcript",
            str(transcript),
            "--checklist",
            str(CHECKLIST),
            "--artifacts-dir",
            str(artifacts),
            "--db",
            str(tmp_path / "audits.db"),
        ]
    )

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert "spec make_coffee" in captured.out

    report = next(artifacts.glob("*/report.md")).read_text(encoding="utf-8")
    assert "R-STEP-003" in report


def test_missing_clip_returns_two(tmp_path: Path, capsys: object) -> None:
    code = main(["audit", str(tmp_path / "nope.mp4")])
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 2
    assert "error:" in captured.err


def test_unsupported_transcript_returns_two(tmp_path: Path, capsys: object) -> None:
    clip = write_test_video(tmp_path / "clip.avi")
    transcript = tmp_path / "notes.md"
    transcript.write_text("hello", encoding="utf-8")

    code = main(["keyframes", str(clip), "--transcript", str(transcript)])

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 2
    assert "unsupported format" in captured.err


def test_spec_new_writes_reviewable_yaml(tmp_path: Path, capsys: object) -> None:
    output = tmp_path / "coffee.yaml"

    code = main(
        [
            "spec",
            "new",
            "fill the kettle and pour water into the mug",
            "-o",
            str(output),
            "--client",
            "fake",
        ]
    )

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert output.exists()

    text = output.read_text(encoding="utf-8")
    assert "make_coffee" in text
    assert "fill_kettle" in text
    assert "review and edit" in captured.out


def test_checklist_new_remains_an_alias(tmp_path: Path) -> None:
    output = tmp_path / "coffee.yaml"

    code = main(
        [
            "checklist",
            "new",
            "fill the kettle",
            "-o",
            str(output),
            "--client",
            "fake",
        ]
    )

    assert code == 0
    assert output.exists()


def test_audit_can_record_and_replay_a_cassette(tmp_path: Path, capsys: object) -> None:
    clip = write_test_video(tmp_path / "clip.avi")
    transcript = transcript_json(tmp_path / "t.json")
    cassette = tmp_path / "desk.cassette.json"
    base = [
        "audit",
        str(clip),
        "--transcript",
        str(transcript),
        "--artifacts-dir",
        str(tmp_path / "artifacts"),
        "--db",
        str(tmp_path / "audits.db"),
        "--client",
        "fake",
    ]

    assert main([*base, "--record", str(cassette)]) == 0
    assert cassette.exists()

    assert main([*base, "--replay", str(cassette)]) == 0
    assert "cassette replay" in capsys.readouterr().out  # type: ignore[attr-defined]


@pytest.mark.skipif(
    importlib.util.find_spec("instructor") is not None,
    reason="the llm extra is installed, so the client can be constructed",
)
def test_ollama_without_the_llm_extra_explains_how_to_fix(tmp_path: Path, capsys: object) -> None:
    clip = write_test_video(tmp_path / "clip.avi")

    code = main(
        [
            "audit",
            str(clip),
            "--client",
            "ollama",
            "--transcript",
            str(transcript_json(tmp_path / "t.json")),
        ]
    )

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 2
    assert "llm extra" in captured.err


def forbid_whisper(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("whisper must not run in this input mode")

    monkeypatch.setattr("insightscope.pipeline.transcribe", boom)


def audit_args(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "audit",
        str(tmp_path / "clip.avi"),
        "--artifacts-dir",
        str(tmp_path / "artifacts"),
        "--db",
        str(tmp_path / "audits.db"),
        *extra,
    ]


def test_transcript_mode_skips_whisper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    write_test_video(tmp_path / "clip.avi")
    forbid_whisper(monkeypatch)

    code = main(audit_args(tmp_path, "--transcript", str(transcript_json(tmp_path / "t.json"))))

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert "transcript (json" in captured.out


def test_spec_mode_skips_whisper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    write_test_video(tmp_path / "clip.avi")
    forbid_whisper(monkeypatch)

    code = main(audit_args(tmp_path, "--spec", str(CHECKLIST)))

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert "spec make_coffee" in captured.out


def test_process_mode_generates_a_spec_and_skips_whisper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    write_test_video(tmp_path / "clip.avi")
    forbid_whisper(monkeypatch)

    code = main(audit_args(tmp_path, "--process", "fill the kettle, then pour water into the mug"))

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert "process text" in captured.out

    generated = list((tmp_path / "artifacts").glob("*/generated_spec.yaml"))
    assert len(generated) == 1
    assert "make_coffee" in generated[0].read_text(encoding="utf-8")


def test_process_file_mode_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_test_video(tmp_path / "clip.avi")
    forbid_whisper(monkeypatch)
    process = tmp_path / "process.txt"
    process.write_text("fill the kettle, then pour water into the mug", encoding="utf-8")

    code = main(audit_args(tmp_path, "--process-file", str(process)))

    assert code == 0


def test_listen_mode_transcribes_the_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    write_test_video(tmp_path / "clip.avi")
    calls: dict[str, object] = {}

    def fake_transcribe(path: Path, *, model_size: str) -> TranscriptBundle:
        calls["path"] = path
        calls["model"] = model_size
        return TranscriptBundle(
            utterances=(
                Utterance(
                    utterance_id="u_0001",
                    text="I filled the kettle",
                    span=TimeSpan(t_start_s=0.0, t_end_s=1.0),
                ),
            ),
            mode="asr",
        )

    monkeypatch.setattr("insightscope.pipeline.transcribe", fake_transcribe)
    monkeypatch.setattr("insightscope.pipeline.has_audio_stream", lambda _path: True)

    code = main(audit_args(tmp_path))

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert calls["model"] == "small.en"
    assert "listen (whisper small.en, 1 segments)" in captured.out

    report = next((tmp_path / "artifacts").glob("*/report.md")).read_text(encoding="utf-8")
    assert "asr transcript" in report


def test_reference_sources_are_mutually_exclusive(tmp_path: Path) -> None:
    write_test_video(tmp_path / "clip.avi")

    with pytest.raises(SystemExit):
        main(
            audit_args(
                tmp_path,
                "--process",
                "fill the kettle",
                "--spec",
                str(CHECKLIST),
            )
        )


def test_transcript_can_accompany_a_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    write_test_video(tmp_path / "clip.avi")
    forbid_whisper(monkeypatch)

    code = main(
        audit_args(
            tmp_path,
            "--transcript",
            str(transcript_json(tmp_path / "t.json")),
            "--spec",
            str(CHECKLIST),
        )
    )

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert "spec make_coffee" in captured.out


def whisper_returning(
    monkeypatch: pytest.MonkeyPatch, text: str = "I closed the laptop"
) -> dict[str, object]:
    calls: dict[str, object] = {}

    def fake_transcribe(path: Path, *, model_size: str) -> TranscriptBundle:
        calls["path"] = path
        calls["model"] = model_size
        return TranscriptBundle(
            utterances=(
                Utterance(
                    utterance_id="u_0001",
                    text=text,
                    span=TimeSpan(t_start_s=0.0, t_end_s=1.0),
                ),
            ),
            mode="asr",
        )

    monkeypatch.setattr("insightscope.pipeline.transcribe", fake_transcribe)
    monkeypatch.setattr("insightscope.pipeline.has_audio_stream", lambda _path: True)
    return calls


def test_listen_with_spec_is_a_hybrid_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    write_test_video(tmp_path / "clip.avi")
    calls = whisper_returning(monkeypatch)

    code = main(audit_args(tmp_path, "--listen", "--spec", str(CHECKLIST)))

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert calls["model"] == "small.en"
    assert "hybrid (listen + spec make_coffee" in captured.out

    report = next((tmp_path / "artifacts").glob("*/report.md")).read_text(encoding="utf-8")
    assert "### Process / Spec Compliance" in report
    assert "### Speech / Transcript Verification" in report
    assert "R-STEP-003" in report


def test_listen_with_process_is_a_hybrid_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    write_test_video(tmp_path / "clip.avi")
    whisper_returning(monkeypatch)

    code = main(audit_args(tmp_path, "--listen", "--process", "fill the kettle, then pour water"))

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert "hybrid (listen + process text → spec make_coffee" in captured.out
    assert list((tmp_path / "artifacts").glob("*/generated_spec.yaml"))


def test_spec_only_run_is_reported_as_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    write_test_video(tmp_path / "clip.avi")
    forbid_whisper(monkeypatch)

    code = main(audit_args(tmp_path, "--spec", str(CHECKLIST)))

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert "input:     spec make_coffee" in captured.out
    assert "hybrid (" not in captured.out


def test_listen_and_transcript_are_mutually_exclusive(tmp_path: Path) -> None:
    write_test_video(tmp_path / "clip.avi")

    with pytest.raises(SystemExit):
        main(
            audit_args(
                tmp_path,
                "--listen",
                "--transcript",
                str(transcript_json(tmp_path / "t.json")),
            )
        )


def test_open_ended_report_keeps_a_single_table(tmp_path: Path) -> None:
    write_test_video(tmp_path / "clip.avi")

    code = main(audit_args(tmp_path, "--transcript", str(transcript_json(tmp_path / "t.json"))))

    assert code == 0
    report = next((tmp_path / "artifacts").glob("*/report.md")).read_text(encoding="utf-8")
    assert "### Process / Spec Compliance" not in report
    assert "### Speech / Transcript Verification" not in report


def test_spec_report_splits_findings(tmp_path: Path) -> None:
    write_test_video(tmp_path / "clip.avi")

    code = main(audit_args(tmp_path, "--spec", str(CHECKLIST)))

    assert code == 0
    report = next((tmp_path / "artifacts").glob("*/report.md")).read_text(encoding="utf-8")
    assert "### Process / Spec Compliance" in report
    assert "### Speech / Transcript Verification" in report
    assert "No speech or observation conflicts." in report


def test_listen_fails_fast_when_the_video_has_no_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    write_test_video(tmp_path / "clip.avi", flash_at=None)
    monkeypatch.setattr("insightscope.pipeline.has_audio_stream", lambda _path: False)

    code = main(audit_args(tmp_path))

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 2
    assert "no audio track" in captured.err
    assert "--audio" in captured.err


def test_audio_flag_transcribes_a_separate_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    write_test_video(tmp_path / "clip.avi", flash_at=None)
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"RIFF")
    calls = whisper_returning(monkeypatch)

    code = main(audit_args(tmp_path, "--audio", str(voice)))

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert calls["path"] == voice
    assert "audio (" in captured.out
    assert str(voice) in captured.out


def test_audio_with_spec_is_a_hybrid_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: object
) -> None:
    write_test_video(tmp_path / "clip.avi", flash_at=None)
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"RIFF")
    whisper_returning(monkeypatch)

    code = main(audit_args(tmp_path, "--audio", str(voice), "--spec", str(CHECKLIST)))

    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert code == 0
    assert "hybrid (audio + spec make_coffee" in captured.out


def test_audio_and_listen_are_mutually_exclusive(tmp_path: Path) -> None:
    write_test_video(tmp_path / "clip.avi")
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"RIFF")

    with pytest.raises(SystemExit):
        main(audit_args(tmp_path, "--audio", str(voice), "--listen"))
