"""Pure spec-editing helpers: validation, filenames, and button predicates."""

from __future__ import annotations

from pathlib import Path

import pytest

from insightscope.domain.checklist import ChecklistError
from insightscope.ui.specs import (
    NEW_SPEC,
    delete_enabled,
    delete_spec,
    generate_enabled,
    normalise_filename,
    save_enabled,
    save_new_spec,
    validate_spec_yaml,
    validation_message,
)

VALID = """name: make_tea
expected_objects: [mug]
steps:
  - step_id: fill_kettle
"""


def test_valid_yaml_passes() -> None:
    assert validate_spec_yaml(VALID) == (True, "Valid.")
    assert validation_message(VALID) == ""


def test_invalid_yaml_is_explained() -> None:
    valid, message = validate_spec_yaml("name: [unclosed")
    assert valid is False
    assert "YAML" in message

    valid, message = validate_spec_yaml("just a string")
    assert valid is False
    assert "mapping" in message

    valid, message = validate_spec_yaml("name: ''")
    assert valid is False
    assert "name" in message


def test_empty_yaml_is_not_valid_but_has_no_status_line() -> None:
    assert validate_spec_yaml("   ") == (False, "Spec is empty.")
    assert validation_message("   ") == ""


def test_filename_normalisation_appends_yaml() -> None:
    assert normalise_filename("brew_tea") == "brew_tea.yaml"
    assert normalise_filename("brew_tea.yaml") == "brew_tea.yaml"


@pytest.mark.parametrize("filename", ["", "  ", "../escape.yaml", "nested/x.yaml"])
def test_filename_rejects_paths(filename: str) -> None:
    with pytest.raises(ChecklistError):
        normalise_filename(filename)


def test_existing_spec_save_needs_valid_and_changed_text() -> None:
    assert save_enabled("make_tea.yaml", VALID, VALID, "") is False
    assert save_enabled("make_tea.yaml", VALID + "\n", VALID, "") is False
    changed = VALID.replace("make_tea", "make_strong_tea")
    assert save_enabled("make_tea.yaml", changed, VALID, "") is True
    assert save_enabled("make_tea.yaml", "name: [bad", VALID, "") is False


def test_new_spec_save_needs_a_filename() -> None:
    assert save_enabled(NEW_SPEC, VALID, "", "") is False
    assert save_enabled(NEW_SPEC, VALID, "", "brew_tea.yaml") is True


def test_generate_needs_filename_and_process() -> None:
    assert generate_enabled(NEW_SPEC, "", "brew tea") is False
    assert generate_enabled(NEW_SPEC, "brew_tea.yaml", "") is False
    assert generate_enabled(NEW_SPEC, "brew_tea.yaml", "brew tea") is True


def test_generate_is_available_for_the_selected_spec() -> None:
    assert generate_enabled("make_tea.yaml", "", "brew tea") is True
    assert generate_enabled("make_tea.yaml", "", "") is False


def test_save_new_spec_refuses_duplicates(tmp_path: Path) -> None:
    specs = tmp_path / "specs"
    saved = save_new_spec(VALID, "make_tea", specs)
    assert saved.path.name == "make_tea.yaml"

    with pytest.raises(ChecklistError, match="already exists"):
        save_new_spec(VALID, "make_tea.yaml", specs)


def test_delete_spec_removes_the_file(tmp_path: Path) -> None:
    specs = tmp_path / "specs"
    save_new_spec(VALID, "make_tea", specs)

    delete_spec("make_tea.yaml", specs)

    assert not (specs / "make_tea.yaml").exists()


def test_delete_spec_rejects_new_spec_marker(tmp_path: Path) -> None:
    with pytest.raises(ChecklistError, match="cannot delete"):
        delete_spec(NEW_SPEC, tmp_path / "specs")


@pytest.mark.parametrize("filename", ["../escape.yaml", "nested/x.yaml", "/etc/passwd"])
def test_delete_spec_rejects_paths(filename: str, tmp_path: Path) -> None:
    with pytest.raises(ChecklistError):
        delete_spec(filename, tmp_path / "specs")


def test_delete_spec_reports_missing_files(tmp_path: Path) -> None:
    specs = tmp_path / "specs"
    specs.mkdir()

    with pytest.raises(ChecklistError, match="no such spec"):
        delete_spec("make_tea.yaml", specs)


def test_delete_enabled_only_for_existing_specs() -> None:
    assert delete_enabled("make_tea.yaml") is True
    assert delete_enabled(NEW_SPEC) is False
    assert delete_enabled("") is False
