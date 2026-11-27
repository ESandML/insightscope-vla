"""Spec browsing and persistence for the UI.

Thin wrappers over ``domain.checklist`` so the Gradio layer never builds paths by hand.
Every read and write is confined to the specs directory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from insightscope.domain.checklist import (
    ChecklistError,
    ChecklistSpec,
    list_specs,
    resolve_spec_path,
    save_spec_to_dir,
)


@dataclass(frozen=True, slots=True)
class SavedSpec:
    path: Path
    spec: ChecklistSpec
    text: str


def spec_names(specs_dir: Path) -> list[str]:
    return [path.name for path in list_specs(specs_dir)]


def default_spec_name(specs_dir: Path) -> str | None:
    names = spec_names(specs_dir)
    if "make_tea.yaml" in names:
        return "make_tea.yaml"
    return names[0] if names else None


def read_spec_text(name: str, specs_dir: Path) -> str:
    return resolve_spec_path(name, specs_dir).read_text(encoding="utf-8")


def initial_spec_text(specs_dir: Path) -> str:
    """The YAML the page should show before the user touches anything."""
    name = default_spec_name(specs_dir)
    if name is None:
        return ""
    try:
        return read_spec_text(name, specs_dir)
    except ChecklistError:
        return ""


def parse_spec_text(text: str) -> ChecklistSpec:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ChecklistError("audit spec must be a YAML mapping")
    try:
        return ChecklistSpec.model_validate(raw)
    except Exception as exc:
        raise ChecklistError(f"invalid audit spec: {exc}") from exc


def save_spec_text(
    text: str,
    specs_dir: Path,
    filename: str | None = None,
) -> SavedSpec:
    """Save YAML, keeping the on-disk name and the spec ``name`` consistent.

    When ``filename`` is given (the spec currently selected in the dropdown), the saved
    spec adopts that file's stem as its name. Editing ``make_tea.yaml`` therefore updates
    one file instead of creating a duplicate under a different name.
    """
    spec = parse_spec_text(text)
    target = Path(filename) if filename else Path(f"{spec.name}.yaml")
    if target.suffix == "":
        target = target.with_suffix(".yaml")

    if spec.name != target.stem:
        spec = spec.model_copy(update={"name": target.stem})

    path = save_spec_to_dir(spec, specs_dir, target.name)
    return SavedSpec(path=path, spec=spec, text=_dump_text(spec))


def _dump_text(spec: ChecklistSpec) -> str:
    return yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True)


def dropdown_update(specs_dir: Path, selected: str | None = None) -> object:
    """Build a Gradio dropdown update with the current saved specs."""
    import gradio as gr

    names = spec_names(specs_dir)
    value = selected if selected in names else (names[0] if names else None)
    return gr.update(choices=names, value=value)
