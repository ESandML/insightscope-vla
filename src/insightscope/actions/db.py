"""The local audit log: one SQLite file, three tables, no server.

Writes are upserts keyed by content ids. That is what makes ``dispatch_actions`` safe
to re-run after a checkpoint resume: the same run and the same finding cannot create a
second row. Schema changes must be additive, and ``PRAGMA user_version`` records which
shape a file has.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from insightscope.domain.models import AuditReport, Finding

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL,
    source_path   TEXT NOT NULL,
    duration_s    REAL NOT NULL,
    n_findings    INTEGER NOT NULL,
    n_annotated   INTEGER NOT NULL,
    report        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
    finding_id  TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    rule_id     TEXT NOT NULL,
    kind        TEXT NOT NULL,
    severity    TEXT NOT NULL,
    subject_id  TEXT NOT NULL,
    attribute   TEXT,
    said_value  TEXT,
    seen_value  TEXT,
    at_s        REAL,
    status      TEXT NOT NULL,
    note        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS flagged_frames (
    finding_id  TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    path        TEXT NOT NULL,
    PRIMARY KEY (finding_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_findings_run ON findings (run_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(_SCHEMA)
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    return connection


def record_run(
    *,
    db_path: Path,
    report: AuditReport,
    source_path: str,
    duration_s: float,
    flagged: Sequence[tuple[str, str]] = (),
    now: datetime | None = None,
) -> None:
    """Upsert the run, its findings, and the paths of annotated frames."""
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    connection = connect(db_path)
    try:
        with connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO runs
                    (run_id, created_at, status, source_path, duration_s,
                     n_findings, n_annotated, report)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.run_id,
                    stamp,
                    report.status,
                    source_path,
                    duration_s,
                    len(report.findings),
                    len(flagged),
                    report.markdown,
                ),
            )
            for finding in report.findings:
                discrepancy = finding.discrepancy
                connection.execute(
                    """
                    INSERT OR REPLACE INTO findings
                        (finding_id, run_id, rule_id, kind, severity, subject_id,
                         attribute, said_value, seen_value, at_s, status, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding.finding_id,
                        report.run_id,
                        discrepancy.rule_id,
                        discrepancy.kind,
                        discrepancy.severity,
                        discrepancy.subject_id,
                        discrepancy.attribute.value if discrepancy.attribute else None,
                        discrepancy.said_value,
                        discrepancy.seen_value,
                        _at_seconds(finding),
                        finding.status,
                        discrepancy.note,
                    ),
                )
            for finding_id, path in flagged:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO flagged_frames (finding_id, run_id, path)
                    VALUES (?, ?, ?)
                    """,
                    (finding_id, report.run_id, path),
                )
    finally:
        connection.close()


def history(db_path: Path, *, limit: int = 20) -> list[dict[str, object]]:
    """Recent runs, newest first. Returns [] when the database does not exist yet."""
    if not db_path.exists():
        return []
    connection = connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT run_id, created_at, status, source_path, n_findings, n_annotated
            FROM runs
            ORDER BY created_at DESC, run_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def schema_version(db_path: Path) -> int:
    connection = connect(db_path)
    try:
        row = connection.execute("PRAGMA user_version").fetchone()
        return int(row[0])
    finally:
        connection.close()


def _at_seconds(finding: Finding) -> float | None:
    discrepancy = finding.discrepancy
    for span in (discrepancy.span_said, discrepancy.span_seen):
        if span is not None:
            return float(span.t_start_s)
    return None
