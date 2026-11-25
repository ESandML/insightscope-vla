"""The subject registry: the join point between what was said and what was seen."""

from pathlib import Path

from insightscope.domain.checklist import load_checklist
from insightscope.domain.models import Assertion, Provenance, TimeSpan, make_assertion_id
from insightscope.domain.ontology import Attribute
from insightscope.domain.registry import SubjectRegistry

FIXTURE = Path(__file__).parent.parent / "fixtures" / "checklists" / "desk.yaml"


def assertion(subject: str, modality: str, start: float = 0.0) -> Assertion:
    span = TimeSpan(t_start_s=start, t_end_s=start + 1.0)
    attribute = Attribute.PRESENCE
    return Assertion(
        assertion_id=make_assertion_id(modality, subject, attribute, True, span),  # type: ignore[arg-type]
        modality=modality,  # type: ignore[arg-type]
        subject_id=subject,
        attribute=attribute,
        value=True,
        span=span,
        provenance=Provenance(model="fake"),
    )


def test_open_ended_registry_only_knows_what_was_mentioned() -> None:
    registry = SubjectRegistry.build(said=[assertion("mug", "acoustic")])
    assert registry.ids() == ("mug",)
    assert registry.expected_ids() == ()


def test_checklist_seeds_expected_subjects() -> None:
    checklist = load_checklist(FIXTURE)
    registry = SubjectRegistry.build(checklist=checklist)
    assert "coffee_mug" in registry.expected_ids()
    assert "close_laptop" in registry.expected_ids()
    assert registry.expected_not_done  # nothing claimed yet


def test_seen_and_said_are_tracked_separately() -> None:
    registry = SubjectRegistry.build(
        said=[assertion("laptop", "acoustic"), assertion("mug", "acoustic")],
        seen=[assertion("laptop", "vision"), assertion("pen", "vision")],
    )
    assert registry.seen_not_said == ("pen",)
    assert registry.said_not_seen == ("mug",)
    assert set(registry.said_ids()) == {"laptop", "mug"}


def test_checklist_plus_transcript_merges_by_canonical_id() -> None:
    checklist = load_checklist(FIXTURE)
    registry = SubjectRegistry.build(
        said=[assertion("coffee_mug", "acoustic")],
        seen=[assertion("coffee_mug", "vision")],
        checklist=checklist,
    )
    assert registry.refs["coffee_mug"].said and registry.refs["coffee_mug"].seen
    assert registry.refs["coffee_mug"].expected
