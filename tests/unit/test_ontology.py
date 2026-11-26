"""Value coercion: the last line of defence before a model's guess reaches a rule."""

import pytest

from insightscope.domain.ontology import (
    Attribute,
    OntologyError,
    coerce_value,
    normalize_action,
    normalize_token,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(True, True), ("yes", True), ("Present", True), ("no", False), ("0", False), (0, False)],
)
def test_presence_accepts_common_phrasings(raw: object, expected: bool) -> None:
    assert coerce_value(Attribute.PRESENCE, raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"), [("shut", "closed"), ("Open", "open"), ("cracked", "ajar")]
)
def test_open_closed_synonyms(raw: str, expected: str) -> None:
    assert coerce_value(Attribute.OPEN_CLOSED, raw) == expected


def test_count_parses_numeric_strings() -> None:
    assert coerce_value(Attribute.COUNT, "3") == 3
    assert coerce_value(Attribute.COUNT, 3) == 3


@pytest.mark.parametrize("raw", [True, -1, "many", 2.5, 5000])
def test_count_rejects_nonsense(raw: object) -> None:
    with pytest.raises(OntologyError):
        coerce_value(Attribute.COUNT, raw)


def test_location_is_normalised() -> None:
    assert coerce_value(Attribute.LOCATION, "Left of Laptop") == "left_of_laptop"


def test_unknown_value_is_an_error_not_a_guess() -> None:
    with pytest.raises(OntologyError):
        coerce_value(Attribute.OPEN_CLOSED, "partially")


def test_step_attribute_is_not_an_object_property() -> None:
    assert Attribute.STEP_COMPLETED.subject_kind == "step"
    assert Attribute.PRESENCE.subject_kind == "object"


@pytest.mark.parametrize(("raw", "expected"), [("done", True), ("no", False), (True, True)])
def test_action_completed_uses_boolean_normalisation(raw: object, expected: bool) -> None:
    assert coerce_value(Attribute.ACTION_COMPLETED, raw) is expected


def test_action_completed_is_an_object_action_not_a_step() -> None:
    assert Attribute.ACTION_COMPLETED.subject_kind == "object"


def test_normalize_action_folds_case_and_spacing() -> None:
    assert normalize_action("Wipe the Counter") == "wipe_the_counter"


def test_empty_action_is_an_error() -> None:
    with pytest.raises(OntologyError):
        normalize_action("   ")


def test_normalize_token_collapses_punctuation() -> None:
    assert normalize_token("  On the   TRAY! ") == "on_the_tray"
