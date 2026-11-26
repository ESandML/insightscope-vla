"""Checklist loading, validation, and round-tripping."""

from pathlib import Path

import pytest

from insightscope.domain.checklist import (
    ChecklistError,
    ChecklistSpec,
    StepSpec,
    dump_checklist,
    load_checklist,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "checklists" / "make_coffee.yaml"


def test_loads_demo_checklist() -> None:
    spec = load_checklist(FIXTURE)
    assert spec.name == "make_coffee"
    assert spec.step_ids() == (
        "fill_kettle",
        "boil_kettle",
        "spoon_coffee",
        "pour_water",
        "stir_coffee",
    )
    assert "mug" in spec.expected_objects


def test_alias_table_covers_objects_and_steps() -> None:
    spec = load_checklist(FIXTURE)
    table = spec.alias_table()
    assert table.resolve("cup") == "mug"
    assert table.resolve("electric kettle") == "kettle"


def test_step_ids_must_be_unique() -> None:
    with pytest.raises(ValueError, match="duplicate step"):
        ChecklistSpec(
            name="bad",
            steps=[StepSpec(step_id="do_it"), StepSpec(step_id="do_it")],
        )


def test_step_id_must_be_snake_case() -> None:
    with pytest.raises(ValueError):
        StepSpec(step_id="Close Laptop")


def test_alias_for_unknown_object_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown subject"):
        ChecklistSpec(
            name="bad",
            expected_objects=["laptop"],
            aliases={"teapot": ["kettle"]},
        )


def test_duplicate_objects_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate object"):
        ChecklistSpec(name="bad", expected_objects=["Laptop", "laptop"])


def test_round_trip_is_human_readable(tmp_path: Path) -> None:
    spec = load_checklist(FIXTURE)
    out = dump_checklist(spec, tmp_path / "nested" / "coffee.yaml")

    text = out.read_text(encoding="utf-8")
    assert "make_coffee" in text
    assert "steps:" in text
    assert load_checklist(out) == spec


def test_missing_file_reports_the_path(tmp_path: Path) -> None:
    missing = tmp_path / "nope.yaml"
    with pytest.raises(ChecklistError, match=r"nope\.yaml"):
        load_checklist(missing)
