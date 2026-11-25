"""Synthesis, deterministic validation, and critique.

Order matters and is deliberate: validate first, critique second. There is no reason
to spend model tokens asking whether a citation resolves when Python already knows.
Validation failures go straight back to synthesis; only a clean draft reaches the
critic.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from insightscope.clients.base import (
    ClientError,
    CritiqueRequest,
    SynthesisRequest,
    TextClient,
)
from insightscope.graph.nodes._common import (
    NodeUpdate,
    attempt,
    cycle_of,
    failed,
)
from insightscope.graph.state import (
    AuditState,
    ValidationProblem,
    ValidationResult,
)

Node = Callable[[AuditState], Awaitable[NodeUpdate]]


def make_synthesize(client: TextClient) -> Node:
    async def node(state: AuditState) -> NodeUpdate:
        reconciliation = state.get("reconciliation")
        if reconciliation is None:
            return {
                "fatal": "synthesize: no reconciliation in state",
                "trace": ["synthesize"],
                "status": "failed",
            }

        previous = state.get("draft")
        issues = tuple(state.get("pending_issues") or ())
        cycle = cycle_of(state)

        try:
            draft = await client.synthesize(
                SynthesisRequest(
                    findings=reconciliation.findings,
                    evidence=state["evidence"],
                    previous_markdown=previous.markdown if previous is not None else None,
                    issues=issues,
                )
            )
        except ClientError as exc:
            return failed("synthesize", exc, cycle)

        return {
            "draft": draft,
            "attempts": [attempt("synthesize", cycle)],
            "pending_issues": [],
            "trace": ["synthesize"],
            "status": "synthesizing",
        }

    return node


def validate(state: AuditState) -> NodeUpdate:
    """Citation checks that must hold before a critic sees the draft."""
    draft = state.get("draft")
    reconciliation = state.get("reconciliation")
    findings = reconciliation.findings if reconciliation is not None else ()

    problems: list[ValidationProblem] = []
    if draft is None or not draft.markdown.strip():
        problems.append(ValidationProblem(code="empty_draft", message="draft is empty"))

    if draft is not None:
        known = {finding.finding_id for finding in findings}
        cited = set(draft.cited_finding_ids)
        for reference in sorted(cited - known):
            problems.append(
                ValidationProblem(
                    code="unknown_citation",
                    ref=reference,
                    message="citation does not resolve to a finding",
                )
            )
        confirmed_major = {
            finding.finding_id
            for finding in findings
            if finding.severity in ("blocker", "major") and finding.status == "confirmed"
        }
        for reference in sorted(confirmed_major - cited):
            problems.append(
                ValidationProblem(
                    code="missing_citation",
                    ref=reference,
                    message="confirmed major finding is not cited",
                )
            )

    result = ValidationResult(ok=not problems, problems=tuple(problems))
    return {
        "validation": result,
        "trace": ["validate"],
        "status": "critiquing" if result.ok else "validating",
    }


def make_critique(client: TextClient) -> Node:
    async def node(state: AuditState) -> NodeUpdate:
        draft = state.get("draft")
        if draft is None:
            return {
                "fatal": "critique: no draft to review",
                "trace": ["critique"],
                "status": "failed",
            }

        reconciliation = state.get("reconciliation")
        findings = reconciliation.findings if reconciliation is not None else ()
        cycle = cycle_of(state)

        try:
            critique = await client.critique(CritiqueRequest(draft=draft, findings=findings))
        except ClientError as exc:
            return failed("critique", exc, cycle)

        return {
            "critique": critique,
            "critique_history": [critique],
            "attempts": [attempt("critique", cycle, verdict=critique.verdict)],
            "trace": ["critique"],
        }

    return node
