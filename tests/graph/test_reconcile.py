"""End-to-end reconciliation: resolution, alignment, rules, adjudication, stats."""

from tests.support import claim, manifest, observation, proposal

from insightscope.config import RunConfig
from insightscope.domain.checklist import ChecklistSpec, StepSpec
from insightscope.domain.ontology import Attribute
from insightscope.reconcile import reconcile

COFFEE = ChecklistSpec(
    name="make_coffee",
    steps=[StepSpec(step_id="fill_kettle"), StepSpec(step_id="pour_water")],
)


def coffee_run(checklist: ChecklistSpec | None) -> object:
    return reconcile(
        claims=[
            claim("mug", Attribute.LOCATION, "on_counter", start=20.0),
            claim("fill_kettle", Attribute.STEP_COMPLETED, True, start=12.0),
        ],
        observations=[
            observation("mug", Attribute.LOCATION, "in_sink", start=20.0),
            observation("fill_kettle", Attribute.STEP_COMPLETED, True, start=12.0),
        ],
        evidence=manifest(),
        config=RunConfig(checklist=checklist),
    )


def test_scenario_produces_expected_findings_in_order() -> None:
    result = coffee_run(COFFEE)
    rules = [finding.discrepancy.rule_id for finding in result.findings]
    assert rules == ["R-STEP-003", "R-LOC-001"]

    assert result.stats.n_claims == 2
    assert result.stats.n_observations == 2
    assert result.stats.counts_by_rule == {"R-LOC-001": 1, "R-STEP-003": 1}
    assert result.stats.counts_by_severity == {"major": 1, "minor": 1}


def test_spec_gate_changes_the_result() -> None:
    with_spec = coffee_run(COFFEE)
    without = coffee_run(None)
    assert "R-STEP-003" in {f.discrepancy.rule_id for f in with_spec.findings}
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


def test_spec_aliases_are_applied_during_resolution() -> None:
    aliased = ChecklistSpec(
        name="aliased",
        expected_objects=["mug"],
        aliases={"mug": ["cup"]},
    )
    result = reconcile(
        claims=[claim("unspecified_target", Attribute.OPEN_CLOSED, "open", start=30.0)],
        observations=[observation("mug", Attribute.OPEN_CLOSED, "closed", start=30.0)],
        proposals=[proposal("the cup", start=30.0)],
        evidence=manifest(),
        config=RunConfig(checklist=aliased),
    )
    assert result.claims[0].subject_id == "mug"
    assert [f.discrepancy.rule_id for f in result.findings] == ["R-STATE-001"]


def test_findings_ids_are_unique() -> None:
    result = coffee_run(COFFEE)
    ids = [finding.finding_id for finding in result.findings]
    assert len(ids) == len(set(ids))


def test_result_is_deterministic_and_serialisable() -> None:
    first = coffee_run(COFFEE)
    second = coffee_run(COFFEE)
    assert first.model_dump_json() == second.model_dump_json()

    from insightscope.reconcile import ReconcileResult

    restored = ReconcileResult.model_validate_json(first.model_dump_json())
    assert restored == first


def test_no_findings_for_a_clean_run() -> None:
    result = reconcile(
        claims=[claim("kettle", Attribute.PRESENCE, True)],
        observations=[observation("kettle", Attribute.PRESENCE, True)],
        evidence=manifest(),
        config=RunConfig(),
    )
    assert result.findings == ()
    assert result.stats.counts_by_rule == {}
