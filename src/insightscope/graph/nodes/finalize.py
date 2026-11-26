"""Building the report at three levels of confidence.

``finalize``          the critic accepted the draft
``finalize_caveats``  we ran out of budget or the critic kept objecting; ship what we
                      have, and say plainly what was not established
``escalate``          something failed hard; a human needs to look at this

All three render the same deterministic table, so the difference is visible in the
status line and the caveats rather than buried in prose.
"""

from __future__ import annotations

from collections.abc import Sequence

from insightscope.domain.models import (
    AuditReport,
    ReconcileStats,
    ReportProvenance,
)
from insightscope.graph.nodes._common import NodeUpdate
from insightscope.graph.state import AuditState
from insightscope.report.render import render_markdown


def finalize(state: AuditState) -> NodeUpdate:
    return _finish(state, "complete", ())


def finalize_caveats(state: AuditState) -> NodeUpdate:
    return _finish(state, "complete_with_caveats", caveats_for(state))


def escalate(state: AuditState) -> NodeUpdate:
    caveats = list(caveats_for(state))
    fatal = state.get("fatal")
    if fatal:
        caveats.append(f"fatal error: {fatal}")
    return _finish(state, "escalated", tuple(caveats))


def caveats_for(state: AuditState) -> tuple[str, ...]:
    caveats: list[str] = []

    validation = state.get("validation")
    if validation is not None and not validation.ok:
        codes = ", ".join(sorted({problem.code for problem in validation.problems}))
        caveats.append(
            f"deterministic validation failed ({codes}); parts of this report are not "
            "supported by the evidence"
        )

    critique = state.get("critique")
    if critique is not None and critique.verdict == "revise":
        caveats.append(
            f"the critic asked for revision and {len(critique.issues)} issue(s) remained "
            "after the retry budget"
        )

    errors = state.get("errors") or ()
    if errors:
        caveats.append(f"{len(errors)} extraction error(s) were recorded")

    return tuple(caveats)


def _finish(state: AuditState, status: str, caveats: Sequence[str]) -> NodeUpdate:
    evidence = state["evidence"]
    config = state["config"]
    reconciliation = state.get("reconciliation")

    findings = reconciliation.findings if reconciliation is not None else ()
    stats = reconciliation.stats if reconciliation is not None else ReconcileStats()
    draft = state.get("draft")
    narrative = draft.markdown if draft is not None else ""
    run_id = state.get("run_id") or f"run-{evidence.bundle_id}"

    report = AuditReport(
        run_id=run_id,
        status=status,
        markdown=render_markdown(
            run_id=run_id,
            evidence=evidence,
            findings=findings,
            narrative=narrative,
            status=status,
            stats=stats,
            caveats=caveats,
            has_spec=config.checklist is not None,
        ),
        findings=findings,
        stats=stats,
        provenance=ReportProvenance(
            bundle_id=evidence.bundle_id,
            source_path=evidence.source_path,
            transcript_mode=evidence.transcript_mode,
            keyframe_count=len(evidence.keyframes),
            text_model=config.models.text,
            vision_model=config.models.vision,
        ),
        caveats=tuple(caveats),
    )

    return {"report": report, "status": status, "trace": [status]}
