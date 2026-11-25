"""Deterministic side effects: the 'action' in vision-language-action.

Two different failure policies, on purpose:

* The database row is the audit trail. If it cannot be written, the run is not
  trustworthy, so the node marks the run failed.
* The annotated image is a convenience for a human. If OpenCV cannot read a frame,
  record a warning and keep the report.

Both are idempotent: deterministic ids, content-addressed filenames, SQL upserts.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from insightscope.actions.annotate import annotate_finding
from insightscope.actions.db import record_run
from insightscope.domain.models import ActionsSummary
from insightscope.graph.nodes._common import NodeUpdate
from insightscope.graph.state import AuditState, NodeError


def dispatch_actions(state: AuditState) -> NodeUpdate:
    report = state.get("report")
    config = state["config"]
    if report is None:
        return {
            "actions": ActionsSummary(warnings=("no report to dispatch",)),
            "trace": ["dispatch_actions"],
        }

    evidence = state["evidence"]
    keyframes = {keyframe.keyframe_id: keyframe for keyframe in evidence.keyframes}

    written: list[tuple[str, str]] = []
    warnings: list[str] = []

    for finding in report.findings:
        discrepancy = finding.discrepancy
        if discrepancy.span_seen is None or not discrepancy.evidence_refs:
            continue
        reference = discrepancy.evidence_refs[0]
        keyframe = keyframes.get(reference)
        if keyframe is None:
            warnings.append(f"{finding.finding_id}: no keyframe named {reference}")
            continue
        destination = config.artifacts_dir / report.run_id / "flagged" / f"{finding.finding_id}.jpg"
        result = annotate_finding(Path(keyframe.uri), finding, destination)
        if result is None:
            warnings.append(f"{finding.finding_id}: could not read {keyframe.keyframe_id}")
            continue
        written.append((finding.finding_id, str(result)))

    try:
        record_run(
            db_path=config.db_path,
            report=report,
            source_path=evidence.source_path,
            duration_s=evidence.duration_s,
            flagged=written,
        )
    except sqlite3.Error as exc:
        return {
            "actions": ActionsSummary(
                run_logged=False,
                annotated=tuple(path for _, path in written),
                warnings=tuple(warnings),
                db_path=str(config.db_path),
            ),
            "errors": [
                NodeError(
                    node="dispatch_actions",
                    code="db_write_failed",
                    message=str(exc),
                )
            ],
            "fatal": f"dispatch_actions: {exc}",
            "status": "failed",
            "trace": ["dispatch_actions"],
        }

    return {
        "actions": ActionsSummary(
            run_logged=True,
            annotated=tuple(path for _, path in written),
            warnings=tuple(warnings),
            db_path=str(config.db_path),
        ),
        "trace": ["dispatch_actions"],
    }
