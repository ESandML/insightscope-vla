"""Spec browsing and persistence for the UI.

Thin wrappers over ``domain.checklist`` so the Gradio layer never builds paths by hand.
Every read and write is confined to the specs directory.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from insightscope.domain.checklist import (
    ChecklistError,
    ChecklistSpec,
    list_specs,
    resolve_spec_path,
    save_spec_to_dir,
)


def spec_names(specs_dir: Path) -> list[str]:
    return [path.name for path in list_specs(specs_dir)]


def default_spec_name(specs_dir: Path) -> str | None:
    names = spec_names(specs_dir)
    if "make_tea.yaml" in names:
        return "make_tea.yaml"
    return names[0] if names else None


def read_spec_text(name: str, specs_dir: Path) -> str:
    return resolve_spec_path(name, specs_dir).read_text(encoding="utf-8")


def parse_spec_text(text: str) -> ChecklistSpec:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ChecklistError("audit spec must be a YAML mapping")
    try:
        return ChecklistSpec.model_validate(raw)
    except Exception as exc:
        raise ChecklistError(f"invalid audit spec: {exc}") from exc


def save_spec_text(text: str, specs_dir: Path, filename: str | None = None) -> Path:
    spec = parse_spec_text(text)
    return save_spec_to_dir(spec, specs_dir, filename or f"{spec.name}.yaml")


def dropdown_update(specs_dir: Path, selected: str | None = None) -> object:
    """Build a Gradio dropdown update with the current saved specs."""
    import gradio as gr

    names = spec_names(specs_dir)
    value = selected if selected in names else (names[0] if names else None)
    return gr.update(choices=names, value=value)
