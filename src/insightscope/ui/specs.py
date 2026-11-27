"""Spec browsing, validation, and persistence for the UI.

All decisions live here so the Gradio layer only moves values. Filenames are always
explicit: nothing is derived from ``spec.name``, and nothing is overwritten by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from insightscope.domain.checklist import (
    ChecklistError,
    ChecklistSpec,
    list_specs,
    resolve_spec_path,
    save_spec_to_dir,
)

NEW_SPEC = "+ New spec"


@dataclass(frozen=True, slots=True)
class SavedSpec:
    path: Path
    spec: ChecklistSpec
    text: str


def spec_names(specs_dir: Path) -> list[str]:
    return [path.name for path in list_specs(specs_dir)]


def spec_choices(specs_dir: Path) -> list[str]:
    return [NEW_SPEC, *spec_names(specs_dir)]


def default_spec_name(specs_dir: Path) -> str | None:
    names = spec_names(specs_dir)
    if "make_tea.yaml" in names:
        return "make_tea.yaml"
    return names[0] if names else None


def initial_choice(specs_dir: Path) -> str:
    return default_spec_name(specs_dir) or NEW_SPEC


def initial_spec_text(specs_dir: Path) -> str:
    """The YAML the page should show before the user touches anything."""
    name = default_spec_name(specs_dir)
    if name is None:
        return ""
    try:
        return read_spec_text(name, specs_dir)
    except ChecklistError:
        return ""


def read_spec_text(name: str, specs_dir: Path) -> str:
    return resolve_spec_path(name, specs_dir).read_text(encoding="utf-8")


def validate_spec_yaml(text: str) -> tuple[bool, str]:
    """Parse and validate YAML without raising. Returns ``(is_valid, message)``."""
    if not text.strip():
        return False, "Spec is empty."

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return False, f"YAML error: {exc}"

    if not isinstance(raw, dict):
        return False, "Spec must be a YAML mapping."

    try:
        ChecklistSpec.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "spec"
        return False, f"{location}: {first.get('msg', 'invalid value')}"

    return True, "Valid."


def validation_message(text: str) -> str:
    """Markdown for the status line under the editor; empty when valid or blank."""
    if not text.strip():
        return ""
    valid, message = validate_spec_yaml(text)
    return "" if valid else f"**Invalid:** {message}"


def normalise_filename(filename: str) -> str:
    """A plain ``*.yaml`` file name, with no directory components."""
    raw = filename.strip()
    if not raw:
        raise ChecklistError("enter a file name, e.g. make_tea.yaml")
    if "/" in raw or "\\" in raw or raw in {".", ".."}:
        raise ChecklistError(f"{filename}: use a plain file name inside specs/")
    path = Path(raw)
    return raw if path.suffix else f"{raw}.yaml"


def spec_exists(filename: str, specs_dir: Path) -> bool:
    try:
        return (specs_dir / normalise_filename(filename)).exists()
    except ChecklistError:
        return False


def ensure_new_filename(filename: str, specs_dir: Path) -> str:
    """Validate a new filename and refuse an existing one before doing any work."""
    target = normalise_filename(filename)
    if (specs_dir / target).exists():
        raise ChecklistError(
            f"{target} already exists in specs/; choose a different name or select it "
            "from the dropdown"
        )
    return target


def save_enabled(choice: str, text: str, baseline: str, filename: str) -> bool:
    valid, _ = validate_spec_yaml(text)
    if not valid:
        return False
    if choice == NEW_SPEC:
        return bool(filename.strip())
    return text.strip() != baseline.strip()


def generate_enabled(choice: str, filename: str, process_text: str) -> bool:
    return choice == NEW_SPEC and bool(filename.strip()) and bool(process_text.strip())


def parse_spec_text(text: str) -> ChecklistSpec:
    valid, message = validate_spec_yaml(text)
    if not valid:
        raise ChecklistError(message)
    raw = yaml.safe_load(text)
    return ChecklistSpec.model_validate(raw)


def save_new_spec(text: str, filename: str, specs_dir: Path) -> SavedSpec:
    """Save under an explicit new filename; refuse to overwrite anything."""
    target = ensure_new_filename(filename, specs_dir)
    return _write(text, target, specs_dir)


def save_existing_spec(text: str, filename: str, specs_dir: Path) -> SavedSpec:
    """Overwrite a spec the user selected. Its YAML ``name`` is preserved."""
    return _write(text, normalise_filename(filename), specs_dir)


def save_uploaded_spec(text: str, filename: str, specs_dir: Path) -> SavedSpec:
    return save_new_spec(text, filename, specs_dir)


def _write(text: str, target: str, specs_dir: Path) -> SavedSpec:
    spec = parse_spec_text(text)
    path = save_spec_to_dir(spec, specs_dir, target)
    return SavedSpec(path=path, spec=spec, text=_dump_text(spec))


def _dump_text(spec: ChecklistSpec) -> str:
    return yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True)


def dropdown_update(specs_dir: Path, selected: str | None = None) -> object:
    """Gradio dropdown update with ``+ New spec`` first and existing files after."""
    import gradio as gr

    names = spec_choices(specs_dir)
    value = selected if selected in names else names[0]
    return gr.update(choices=names, value=value)
