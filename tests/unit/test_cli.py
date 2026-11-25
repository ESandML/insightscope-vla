"""CLI behaviour: exit codes, printed summaries, and the files left behind."""

import json
from pathlib import Path

from tests.support import write_test_video

from insightscope.actions.db import history
from insightscope.cli import main

CHECKLIST = Path(__file__).parent.parent / "fixtures" / "checklists" / "desk.yaml"


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


def test_checklist_enables_step_rules(tmp_path: Path, capsys: object) -> None:
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
    assert "checklist: pack_the_desk" in captured.out

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
