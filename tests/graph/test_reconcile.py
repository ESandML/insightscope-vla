"""End-to-end reconciliation: resolution, alignment, rules, adjudication, stats."""

from tests.support import claim, manifest, observation, proposal

from insightscope.config import RunConfig
from insightscope.domain.checklist import ChecklistSpec, StepSpec
from insightscope.domain.ontology import Attribute
from insightscope.reconcile import reconcile

CHECKLIST = ChecklistSpec(
    name="two",
    steps=[StepSpec(step_id="close_laptop"), StepSpec(step_id="stow_pen")],
)


def desk_run(checklist: ChecklistSpec | None) -> object:
    return reconcile(
        claims=[
            claim("laptop", Attribute.OPEN_CLOSED, "closed", start=12.0),
            claim("coffee_mug", Attribute.LOCATION, "on_tray", start=20.0),
            claim("close_laptop", Attribute.STEP_COMPLETED, True, start=12.0),
        ],
        observations=[
            observation("laptop", Attribute.OPEN_CLOSED, "open", start=12.0),
            observation("coffee_mug", Attribute.LOCATION, "on_desk", start=20.0),
            observation("close_laptop", Attribute.STEP_COMPLETED, True, start=12.0),
        ],
        evidence=manifest(),
        config=RunConfig(checklist=checklist),
    )


def test_scenario_produces_expected_findings_in_order() -> None:
    result = desk_run(CHECKLIST)
    rules = [finding.discrepancy.rule_id for finding in result.findings]
    assert rules == ["R-STEP-003", "R-STATE-001", "R-LOC-001"]

    assert result.stats.n_claims == 3
    assert result.stats.n_observations == 3
    assert result.stats.counts_by_rule == {
        "R-LOC-001": 1,
        "R-STATE-001": 1,
        "R-STEP-003": 1,
    }
    assert result.stats.counts_by_severity == {"major": 2, "minor": 1}


def test_checklist_gate_changes_the_result() -> None:
    with_checklist = desk_run(CHECKLIST)
    without = desk_run(None)
    assert "R-STEP-003" in {f.discrepancy.rule_id for f in with_checklist.findings}
    assert "R-STEP-003" not in {f.discrepancy.rule_id for f in without.findings}


def test_resolution_feeds_alignment() -> None:
    # Open-ended: no alias table, so "the cup" becomes its own subject, `cup`.
    open_ended = reconcile(
        claims=[claim("unspecified_target", Attribute.OPEN_CLOSED, "open", start=30.0)],
        observations=[observation("cup", Attribute.OPEN_CLOSED, "closed", start=30.0)],
        proposals=[proposal("the cup", start=30.0)],
        evidence=manifest(),
        config=RunConfig(),
    )
    assert open_ended.claims[0].subject_id == "cup"
    assert [f.discrepancy.rule_id for f in open_ended.findings] == ["R-STATE-001"]


def test_checklist_aliases_are_applied_during_resolution() -> None:
    aliased = ChecklistSpec(
        name="aliased",
        expected_objects=["coffee_mug"],
        aliases={"coffee_mug": ["cup"]},
    )
    result = reconcile(
        claims=[claim("unspecified_target", Attribute.OPEN_CLOSED, "open", start=30.0)],
        observations=[observation("coffee_mug", Attribute.OPEN_CLOSED, "closed", start=30.0)],
        proposals=[proposal("the cup", start=30.0)],
        evidence=manifest(),
        config=RunConfig(checklist=aliased),
    )
    assert result.claims[0].subject_id == "coffee_mug"
    assert [f.discrepancy.rule_id for f in result.findings] == ["R-STATE-001"]


def test_findings_ids_are_unique() -> None:
    result = desk_run(CHECKLIST)
    ids = [finding.finding_id for finding in result.findings]
    assert len(ids) == len(set(ids))


def test_result_is_deterministic_and_serialisable() -> None:
    first = desk_run(CHECKLIST)
    second = desk_run(CHECKLIST)
    assert first.model_dump_json() == second.model_dump_json()

    # What the checkpointer will see: JSON in, validated model out.
    from insightscope.reconcile import ReconcileResult

    restored = ReconcileResult.model_validate_json(first.model_dump_json())
    assert restored == first


def test_no_findings_for_a_clean_run() -> None:
    result = reconcile(
        claims=[claim("laptop", Attribute.OPEN_CLOSED, "closed")],
        observations=[observation("laptop", Attribute.OPEN_CLOSED, "closed")],
        evidence=manifest(),
        config=RunConfig(),
    )
    assert result.findings == ()
    assert result.stats.counts_by_rule == {}
