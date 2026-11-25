"""Deterministic Markdown rendering.

The model writes the summary paragraph; everything a reader might check — the table,
the severity order, the times — is generated from ``Finding`` objects. That split is
why a golden-file test is meaningful: the model's prose is stubbed in tests, and any
change to the table is a deliberate change to this file.
"""

from __future__ import annotations

from collections.abc import Sequence

from insightscope.domain.models import (
    EvidenceManifest,
    Finding,
    ReconcileStats,
)


def render_markdown(
    *,
    run_id: str,
    evidence: EvidenceManifest,
    findings: Sequence[Finding],
    narrative: str,
    status: str,
    stats: ReconcileStats | None = None,
    caveats: Sequence[str] = (),
) -> str:
    lines: list[str] = [
        f"# Audit report — {run_id}",
        "",
        f"**Status:** `{status}`  ",
        f"**Source:** `{evidence.source_path}`  ",
        (
            f"**Evidence:** {_count(len(evidence.keyframes), 'keyframe')}, "
            f"{evidence.transcript_mode} transcript"
        ),
        "",
    ]

    if caveats:
        lines += ["## Caveats", ""]
        lines += [f"- {caveat}" for caveat in caveats]
        lines.append("")

    if evidence.notes:
        lines += ["## Evidence notes", ""]
        lines += [f"- {note}" for note in evidence.notes]
        lines.append("")

    lines += ["## Summary", "", narrative.strip() or "_No summary was produced._", ""]

    if findings:
        counts = stats.counts_by_severity if stats is not None else {}
        summary = ", ".join(f"{count} {severity}" for severity, count in counts.items())
        lines += [f"## Findings ({len(findings)})", ""]
        if summary:
            lines += [f"Severity mix: {summary}.", ""]
        lines += [
            "| Severity | Rule | Subject | Said | Seen | When | Status |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        lines += [_finding_row(finding) for finding in findings]
        lines.append("")
    else:
        lines += ["## Findings", "", "No conflicts found.", ""]

    return "\n".join(lines).rstrip() + "\n"


def _finding_row(finding: Finding) -> str:
    discrepancy = finding.discrepancy
    said = _cell(
        f"{discrepancy.said_value} @ {_timestamp(discrepancy.span_said.t_start_s)}"
        if discrepancy.said_value and discrepancy.span_said is not None
        else "—"
    )
    seen = _cell(
        f"{discrepancy.seen_value} @ {_timestamp(discrepancy.span_seen.t_start_s)}"
        if discrepancy.seen_value and discrepancy.span_seen is not None
        else "—"
    )
    return (
        f"| {discrepancy.severity} | `{discrepancy.rule_id}` | "
        f"{_cell(discrepancy.subject_id)} | {said} | {seen} | "
        f"{_when(finding)} | {finding.status} |"
    )


def _when(finding: Finding) -> str:
    spans = [
        span
        for span in (finding.discrepancy.span_said, finding.discrepancy.span_seen)
        if span is not None
    ]
    if not spans:
        return "—"
    return _timestamp(min(span.t_start_s for span in spans))


def _timestamp(seconds: float) -> str:
    minutes, remainder = divmod(max(0.0, seconds), 60.0)
    return f"{int(minutes):02d}:{remainder:04.1f}"


def _count(value: int, noun: str) -> str:
    return f"{value} {noun}" if value == 1 else f"{value} {noun}s"


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()
