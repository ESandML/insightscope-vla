"""Routing as a pure function of state.

No graph is compiled in this file, which is the point: retry and degradation policy
can be tested exhaustively, cheaply, and without a model.
"""

from insightscope.config import LoopConfig, RunConfig
from insightscope.contracts.report import Critique, Issue
from insightscope.graph.policy import (
    budget_left,
    choose_repair_target,
    count_attempts,
    route_after_critique,
    route_after_validate,
)
from insightscope.graph.state import Attempt, ValidationProblem, ValidationResult


def state(**overrides: object) -> dict:  # type: ignore[type-arg]
    base: dict = {"config": RunConfig(), "attempts": [], "cycle": 0}  # type: ignore[type-arg]
    base.update(overrides)
    return base


def issue(target: str = "synthesize", severity: str = "blocker") -> Issue:
    return Issue(
        code="unclear",
        severity=severity,  # type: ignore[arg-type]
        target=target,  # type: ignore[arg-type]
        ref="report",
        message="needs work",
    )


def ok_validation() -> ValidationResult:
    return ValidationResult(ok=True)


def bad_validation() -> ValidationResult:
    return ValidationResult(
        ok=False,
        problems=(ValidationProblem(code="unknown_citation", ref="f_missing"),),
    )


def test_counts_only_the_named_node() -> None:
    attempts = [
        Attempt(node="synthesize"),
        Attempt(node="critique"),
        Attempt(node="synthesize"),
    ]
    assert count_attempts(state(attempts=attempts), "synthesize") == 2
    assert count_attempts(state(attempts=attempts), "critique") == 1


def test_budget_uses_configured_attempts() -> None:
    config = RunConfig(loop=LoopConfig(max_node_attempts=2))
    attempts = [Attempt(node="synthesize"), Attempt(node="synthesize")]
    assert not budget_left(state(config=config, attempts=attempts), "synthesize")


def test_fatal_always_escalates() -> None:
    assert route_after_validate(state(fatal="boom")) == "escalate"
    assert (
        route_after_critique(state(fatal="boom", critique=Critique(verdict="accept"))) == "escalate"
    )


def test_clean_validation_goes_to_critique() -> None:
    assert route_after_validate(state(validation=ok_validation())) == "critique"


def test_failed_validation_repairs_without_calling_the_critic() -> None:
    assert route_after_validate(state(validation=bad_validation())) == "repair_synthesis"


def test_failed_validation_degrades_when_budget_is_gone() -> None:
    config = RunConfig(loop=LoopConfig(max_node_attempts=1))
    attempts = [Attempt(node="synthesize")]
    route = route_after_validate(
        state(config=config, attempts=attempts, validation=bad_validation())
    )
    assert route == "finalize_caveats"


def test_accept_finalizes() -> None:
    assert route_after_critique(state(critique=Critique(verdict="accept"))) == "finalize"


def test_blocker_with_budget_repairs_synthesis() -> None:
    critique = Critique(verdict="revise", issues=[issue(target="synthesize")])
    assert route_after_critique(state(critique=critique)) == "repair_synthesis"


def test_blocker_targeting_extraction_repairs_extraction() -> None:
    critique = Critique(verdict="revise", issues=[issue(target="extract")])
    assert route_after_critique(state(critique=critique)) == "repair_extraction"


def test_minor_issues_do_not_trigger_a_repair() -> None:
    critique = Critique(verdict="revise", issues=[issue(severity="minor")])
    assert route_after_critique(state(critique=critique)) == "finalize_caveats"


def test_repair_cycles_are_capped() -> None:
    config = RunConfig(loop=LoopConfig(max_repair_cycles=1))
    critique = Critique(verdict="revise", issues=[issue()])
    assert (
        route_after_critique(state(config=config, cycle=1, critique=critique)) == "finalize_caveats"
    )


def test_node_attempt_budget_caps_repairs() -> None:
    config = RunConfig(
        loop=LoopConfig(max_node_attempts=1, max_repair_cycles=5),
    )
    critique = Critique(verdict="revise", issues=[issue()])
    attempts = [Attempt(node="synthesize")]
    assert (
        route_after_critique(state(config=config, attempts=attempts, critique=critique))
        == "finalize_caveats"
    )


def test_missing_critique_degrades() -> None:
    assert route_after_critique(state()) == "finalize_caveats"


def test_missing_validation_degrades() -> None:
    assert route_after_validate(state()) == "finalize_caveats"


def test_repair_target_prefers_synthesis_on_a_tie() -> None:
    assert choose_repair_target([issue("extract"), issue("synthesize")]) == "synthesize"
    assert choose_repair_target([issue("extract"), issue("extract")]) == "extract"
