"""Optional, human-inspectable checklists.

A checklist is a YAML file that names the objects and the ordered steps of a task.
It is not a prompt and it is not code: the audit loads it, validates it, and uses it
only to enable the step rules. When ``RunConfig.checklist`` is None the same pipeline
runs in open-ended mode and the step rules are skipped.

The generator (Phase 2) writes one of these for you to edit before running anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from insightscope.domain.aliases import AliasTable, normalize_subject


class ChecklistError(ValueError):
    """Raised when a checklist file cannot be read or fails validation."""


class StepSpec(BaseModel):
    """One step of a task, in catalog order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str = Field(min_length=2, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = ""


class ChecklistSpec(BaseModel):
    """What the audit expects to happen, when the user supplies expectations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    description: str = ""
    expected_objects: list[str] = Field(default_factory=list)
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    steps: list[StepSpec] = Field(default_factory=list)

    @field_validator("expected_objects")
    @classmethod
    def _unique_objects(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        for name in value:
            key = normalize_subject(name)
            if key in seen:
                raise ValueError(f"duplicate object: {name!r}")
            seen.add(key)
        return value

    @model_validator(mode="after")
    def _aliases_point_at_known_subjects(self) -> ChecklistSpec:
        known = {normalize_subject(o) for o in self.expected_objects}
        known |= {normalize_subject(s.step_id) for s in self.steps}
        for key in self.aliases:
            if normalize_subject(key) not in known:
                raise ValueError(f"aliases for unknown subject: {key!r}")
        return self

    @model_validator(mode="after")
    def _unique_steps(self) -> ChecklistSpec:
        ids = [s.step_id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate step ids: {ids}")
        return self

    def alias_table(self) -> AliasTable:
        """Alias table for this checklist, including objects and step ids."""
        groups: dict[str, list[str]] = {
            obj: list(self.aliases.get(obj, [])) for obj in self.expected_objects
        }
        for step in self.steps:
            groups[step.step_id] = list(self.aliases.get(step.step_id, []))
        return AliasTable.from_groups(groups)

    def step_ids(self) -> tuple[str, ...]:
        return tuple(s.step_id for s in self.steps)


def load_checklist(path: str | Path) -> ChecklistSpec:
    """Read and validate a checklist YAML file, with the file path in any error."""
    source = Path(path)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ChecklistError(f"{source}: file not found") from exc
    except yaml.YAMLError as exc:
        raise ChecklistError(f"{source}: invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ChecklistError(f"{source}: expected a mapping at the top level")

    try:
        return ChecklistSpec.model_validate(raw)
    except ValidationError as exc:
        raise ChecklistError(f"{source}: {exc}") from exc


def dump_checklist(spec: ChecklistSpec, path: str | Path) -> Path:
    """Write a checklist back out as YAML for a human to read and edit."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = spec.model_dump(mode="json")
    destination.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return destination


def resolve_spec_path(name_or_file: str | Path, specs_dir: Path) -> Path:
    """Resolve a user-supplied spec reference inside ``specs_dir``.

    Bare names (``make_tea`` or ``make_tea.yaml``) are looked up in the directory.
    Anything containing directories is resolved first and then confined, so ``../``
    and absolute paths outside the directory are rejected rather than read.
    """
    raw = Path(name_or_file)
    # Accept "specs/make_tea.yaml" as well as a bare name, without doubling the prefix.
    if not raw.is_absolute() and raw.parts and raw.parts[0] == specs_dir.name:
        raw = Path(*raw.parts[1:])

    if raw.is_absolute() or raw.parent != Path("."):
        candidate = raw if raw.is_absolute() else specs_dir / raw
    else:
        candidate = specs_dir / raw.name

    if not candidate.suffix:
        candidate = candidate.with_suffix(".yaml")

    resolved = _confined(specs_dir, candidate)
    if not resolved.exists():
        raise ChecklistError(f"{resolved}: spec not found in {specs_dir}")
    return resolved


def list_specs(specs_dir: Path) -> list[Path]:
    """Every YAML spec in ``specs_dir``, sorted by filename."""
    if not specs_dir.exists():
        return []
    found = {
        path
        for pattern in ("*.yaml", "*.yml")
        for path in specs_dir.glob(pattern)
        if path.is_file()
    }
    return sorted(found, key=lambda path: path.name)


def save_spec_to_dir(
    spec: ChecklistSpec,
    specs_dir: Path,
    filename: str | None = None,
) -> Path:
    """Write a spec into ``specs_dir`` under a plain filename.

    The name defaults to ``<spec.name>.yaml``. Directory components are refused: a
    spec is always exactly one file inside the specs directory, never a path.
    """
    raw = Path(filename) if filename is not None else Path(f"{spec.name}.yaml")
    if raw.is_absolute() or raw.parent != Path("."):
        raise ChecklistError(
            f"{filename}: use a plain file name inside {specs_dir}, e.g. make_tea.yaml"
        )
    if not raw.suffix:
        raw = raw.with_suffix(".yaml")

    destination = _confined(specs_dir, specs_dir / raw.name)
    return dump_checklist(spec, destination)


def _confined(specs_dir: Path, candidate: Path) -> Path:
    base = specs_dir.resolve()
    resolved = candidate.resolve()
    if resolved != base and base not in resolved.parents:
        raise ChecklistError(f"{candidate}: outside the specs directory {specs_dir}")
    return resolved
