"""Checklist loading, validation, and round-tripping."""

from pathlib import Path

import pytest

from insightscope.domain.checklist import (
    ChecklistError,
    ChecklistSpec,
    StepSpec,
    dump_checklist,
    list_specs,
    load_checklist,
    resolve_spec_path,
    save_spec_to_dir,
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


def test_resolve_spec_path_accepts_a_bare_name(tmp_path: Path) -> None:
    specs = tmp_path / "specs"
    specs.mkdir()
    target = specs / "make_tea.yaml"
    target.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    assert resolve_spec_path("make_tea.yaml", specs) == target.resolve()
    assert resolve_spec_path("make_tea", specs) == target.resolve()
    assert resolve_spec_path("specs/make_tea.yaml", specs) == target.resolve()


def test_resolve_spec_path_rejects_escapes(tmp_path: Path) -> None:
    specs = tmp_path / "specs"
    specs.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ChecklistError, match="outside the specs directory"):
        resolve_spec_path("../outside.yaml", specs)
    with pytest.raises(ChecklistError, match="outside the specs directory"):
        resolve_spec_path(outside, specs)


def test_resolve_spec_path_reports_a_missing_spec(tmp_path: Path) -> None:
    with pytest.raises(ChecklistError, match="not found"):
        resolve_spec_path("nope", tmp_path / "specs")


def test_list_specs_is_sorted_and_ignores_other_files(tmp_path: Path) -> None:
    specs = tmp_path / "specs"
    specs.mkdir()
    (specs / "b.yaml").write_text("name: b", encoding="utf-8")
    (specs / "a.yml").write_text("name: a", encoding="utf-8")
    (specs / "notes.txt").write_text("hello", encoding="utf-8")

    assert [path.name for path in list_specs(specs)] == ["a.yml", "b.yaml"]
    assert list_specs(tmp_path / "missing") == []


def test_save_spec_to_dir_defaults_to_the_spec_name(tmp_path: Path) -> None:
    spec = load_checklist(FIXTURE)
    specs = tmp_path / "specs"

    path = save_spec_to_dir(spec, specs)

    assert path == (specs / "make_coffee.yaml").resolve()
    assert load_checklist(path) == spec


def test_save_spec_to_dir_refuses_directories(tmp_path: Path) -> None:
    spec = load_checklist(FIXTURE)
    specs = tmp_path / "specs"

    with pytest.raises(ChecklistError, match="plain file name"):
        save_spec_to_dir(spec, specs, "../escape.yaml")
    with pytest.raises(ChecklistError, match="plain file name"):
        save_spec_to_dir(spec, specs, str(tmp_path / "absolute.yaml"))
