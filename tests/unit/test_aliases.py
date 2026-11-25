"""Subject normalisation and alias resolution."""

import pytest

from insightscope.domain.aliases import (
    UNSPECIFIED_TARGET,
    AliasError,
    AliasTable,
    normalize_subject,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("The Coffee Cup", "coffee_cup"),
        ("my  laptop", "laptop"),
        ("Laptop's lid", "laptop_lid"),
        ("TRAY", "tray"),
    ],
)
def test_normalize_subject(raw: str, expected: str) -> None:
    assert normalize_subject(raw) == expected


@pytest.mark.parametrize("raw", ["this", "That", "it", "those"])
def test_pronouns_become_unspecified(raw: str) -> None:
    assert normalize_subject(raw) == UNSPECIFIED_TARGET


def test_empty_subject_is_an_error() -> None:
    with pytest.raises(AliasError):
        normalize_subject("   ")


def test_alias_table_resolves_known_names() -> None:
    table = AliasTable.from_groups({"coffee_mug": ["cup", "mug"]})
    assert table.resolve("the mug") == "coffee_mug"
    assert table.resolve("Cup") == "coffee_mug"


def test_unknown_names_pass_through_normalised() -> None:
    table = AliasTable.from_groups({"laptop": ["macbook"]})
    assert table.resolve("Monitor Stand") == "monitor_stand"


def test_ambiguous_alias_is_rejected_at_build_time() -> None:
    with pytest.raises(AliasError, match="maps to both"):
        AliasTable.from_groups({"coffee_mug": ["cup"], "glass": ["cup"]})


def test_alias_colliding_with_other_canonical_is_rejected() -> None:
    with pytest.raises(AliasError):
        AliasTable.from_groups({"coffee_mug": ["glass"], "glass": []})


def test_pronoun_alias_is_rejected() -> None:
    with pytest.raises(AliasError, match="pronoun"):
        AliasTable.from_groups({"laptop": ["this"]})
