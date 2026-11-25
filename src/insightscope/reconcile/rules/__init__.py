"""The rule registry.

Rules are listed here once, with their gate. Keeping the gate beside the rule (rather
than checking the config inside each function) means you can read this table and know
exactly what runs in open-ended mode, what runs with a checklist, and what is opt-in.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from insightscope.domain.models import Discrepancy
from insightscope.reconcile.context import RuleContext
from insightscope.reconcile.rules import coverage, object_state, omissions, references, steps

RuleFn = Callable[[RuleContext], list[Discrepancy]]


@dataclass(frozen=True, slots=True)
class Rule:
    rule_id: str
    run: RuleFn
    needs_checklist: bool = False
    needs_omissions: bool = False


ALL_RULES: tuple[Rule, ...] = (
    # Coverage first: these explain why other rules stayed silent.
    Rule("R-COVER-001", coverage.coverage_gap),
    Rule("R-COVER-002", coverage.not_reported),
    # Object state, open-ended mode.
    Rule("R-PRES-001", object_state.said_present_seen_absent),
    Rule("R-PRES-002", object_state.said_absent_seen_present),
    Rule("R-STATE-001", object_state.open_closed_mismatch),
    Rule("R-COUNT-001", object_state.count_mismatch),
    Rule("R-LOC-001", object_state.location_mismatch),
    # Checklist only.
    Rule("R-STEP-001", steps.step_unsupported, needs_checklist=True),
    Rule("R-STEP-002", steps.step_order, needs_checklist=True),
    Rule("R-STEP-003", steps.step_missing, needs_checklist=True),
    # Optional.
    Rule("R-OMIT-001", omissions.omitted_change, needs_omissions=True),
    # Honest failures.
    Rule("R-REF-001", references.unresolved_reference),
    Rule("R-SUBJ-001", references.unexpected_subject),
)


def run_rules(ctx: RuleContext) -> list[Discrepancy]:
    """Run every rule whose gate is satisfied, in a fixed order."""
    found: list[Discrepancy] = []
    for rule in ALL_RULES:
        if rule.needs_checklist and ctx.config.checklist is None:
            continue
        if rule.needs_omissions and not ctx.config.flag_omissions:
            continue
        found.extend(rule.run(ctx))
    return found
