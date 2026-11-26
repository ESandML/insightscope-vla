"""Prompt assets and the loader that versions them.

Prompts are files, not string literals: they can be reviewed in a diff, and their
content hash becomes the ``prompt_version`` recorded in every assertion. That is how a
report can later answer "which wording produced this?".
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


class PromptError(RuntimeError):
    """A prompt file is missing, unreadable, or missing a required value."""


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    text: str
    version: str
    path: Path


class PromptLibrary:
    """Loads ``.md`` prompts from a directory, caching by name."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self.directory = Path(directory) if directory is not None else default_prompt_dir()
        self._cache: dict[str, Prompt] = {}

    def load(self, name: str) -> Prompt:
        if name in self._cache:
            return self._cache[name]

        path = self.directory / f"{name}.md"
        if not path.exists():
            raise PromptError(f"{path}: prompt file not found")
        text = path.read_text(encoding="utf-8")
        prompt = Prompt(
            name=name,
            text=text,
            version=hashlib.sha256(text.encode("utf-8")).hexdigest()[:8],
            path=path,
        )
        self._cache[name] = prompt
        return prompt


def default_prompt_dir() -> Path:
    """Installed location first, then the repository checkout."""
    override = os.environ.get("INSIGHTSCOPE_PROMPTS_DIR")
    if override:
        return Path(override)

    installed = Path(__file__).resolve().parent / "_prompts"
    if (installed / "extract_claims.md").exists():
        return installed

    repository = Path(__file__).resolve().parents[3] / "prompts"
    if (repository / "extract_claims.md").exists():
        return repository

    raise PromptError(
        "prompts directory not found; set INSIGHTSCOPE_PROMPTS_DIR or run from the repository"
    )


def render(prompt: Prompt, **values: object) -> str:
    """Replace ``{{name}}`` placeholders, refusing to leave any unfilled."""
    provided = {key: str(value) for key, value in values.items()}
    missing = sorted(
        {match.group(1) for match in _PLACEHOLDER.finditer(prompt.text)} - provided.keys()
    )
    if missing:
        raise PromptError(f"{prompt.path}: missing values for {', '.join(missing)}")
    return _PLACEHOLDER.sub(lambda match: provided[match.group(1)], prompt.text)
