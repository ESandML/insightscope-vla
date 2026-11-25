"""Action layer: annotation output and the SQLite audit log."""

from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from insightscope.actions.annotate import annotate_finding, ascii_text
from insightscope.actions.db import history, record_run, schema_version
from insightscope.domain.models import (
    AuditReport,
    Discrepancy,
    Finding,
    ReportProvenance,
    TimeSpan,
    make_discrepancy_id,
    make_finding_id,
)
from insightscope.domain.ontology import Attribute


def finding(subject: str = "laptop", start: float = 12.0) -> Finding:
    said = TimeSpan(t_start_s=start, t_end_s=start + 1.0)
    seen = TimeSpan(t_start_s=start, t_end_s=start + 1.0)
    discrepancy = Discrepancy(
        discrepancy_id=make_discrepancy_id(
            "R-STATE-001", subject, Attribute.OPEN_CLOSED, said, seen
        ),
        rule_id="R-STATE-001",
        kind="contradiction",
        severity="major",
        subject_id=subject,
        attribute=Attribute.OPEN_CLOSED,
        span_said=said,
        span_seen=seen,
        said_value="closed",
        seen_value="open",
        evidence_refs=("kf_0001",),
        det_confidence=0.9,
    )
    return Finding(
        finding_id=make_finding_id(discrepancy.discrepancy_id),
        discrepancy=discrepancy,
        status="confirmed",
    )


def report(findings: tuple[Finding, ...] = ()) -> AuditReport:
    return AuditReport(
        run_id="run-1",
        status="complete",
        markdown="# report\n",
        findings=findings,
        provenance=ReportProvenance(
            bundle_id="b1",
            source_path="clip.mp4",
            transcript_mode="json",
            keyframe_count=1,
            text_model="fake",
            vision_model="fake",
        ),
    )


def write_image(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), np.zeros((120, 160, 3), dtype=np.uint8))
    return path


def test_annotate_writes_a_readable_image(tmp_path: Path) -> None:
    source = write_image(tmp_path / "kf.jpg")
    destination = tmp_path / "flagged" / "f1.jpg"

    written = annotate_finding(source, finding(), destination)

    assert written == destination
    image = cv2.imread(str(destination))
    assert image is not None
    assert image.shape == (120, 160, 3)


def test_annotate_is_idempotent(tmp_path: Path) -> None:
    source = write_image(tmp_path / "kf.jpg")
    destination = tmp_path / "flagged" / "f1.jpg"

    first = annotate_finding(source, finding(), destination)
    second = annotate_finding(source, finding(), destination)

    assert first == second
    assert len(list((tmp_path / "flagged").iterdir())) == 1


def test_missing_source_is_a_warning_not_a_crash(tmp_path: Path) -> None:
    assert annotate_finding(tmp_path / "nope.jpg", finding(), tmp_path / "out.jpg") is None


def test_ascii_text_strips_unrepresentable_characters() -> None:
    assert ascii_text("café — lid") == "caf lid"
    assert ascii_text("laptop") == "laptop"


def test_record_run_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "audits.db"
    payload = report((finding(),))
    stamp = datetime(2026, 1, 1, tzinfo=UTC)

    record_run(
        db_path=db,
        report=payload,
        source_path="clip.mp4",
        duration_s=60.0,
        flagged=(("f1", "/tmp/f1.jpg"),),
        now=stamp,
    )
    record_run(
        db_path=db,
        report=payload,
        source_path="clip.mp4",
        duration_s=60.0,
        flagged=(("f1", "/tmp/f1.jpg"),),
        now=stamp,
    )

    import sqlite3

    connection = sqlite3.connect(db)
    try:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM flagged_frames").fetchone()[0] == 1
    finally:
        connection.close()


def test_history_lists_recent_runs(tmp_path: Path) -> None:
    db = tmp_path / "audits.db"
    assert history(db) == []

    record_run(
        db_path=db,
        report=report(),
        source_path="clip.mp4",
        duration_s=60.0,
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    rows = history(db)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "run-1"
    assert rows[0]["status"] == "complete"


def test_schema_is_versioned(tmp_path: Path) -> None:
    assert schema_version(tmp_path / "audits.db") == 1


@pytest.mark.parametrize("severity", ["major"])
def test_record_finding_values_round_trip(tmp_path: Path, severity: str) -> None:
    db = tmp_path / "audits.db"
    record_run(
        db_path=db,
        report=report((finding(),)),
        source_path="clip.mp4",
        duration_s=60.0,
    )
    import sqlite3

    connection = sqlite3.connect(db)
    try:
        row = connection.execute(
            "SELECT rule_id, said_value, seen_value, severity FROM findings"
        ).fetchone()
    finally:
        connection.close()
    assert row == ("R-STATE-001", "closed", "open", severity)
