"""Prompt loading, versioning, and placeholder rendering."""

from pathlib import Path

import pytest

from insightscope.clients.prompts import (
    PromptError,
    PromptLibrary,
    default_prompt_dir,
    render,
)


def test_repository_prompts_are_found() -> None:
    directory = default_prompt_dir()
    assert (directory / "extract_claims.md").exists()
    assert (directory / "verify_keyframe.md").exists()
    assert (directory / "synthesize_report.md").exists()
    assert (directory / "critique_report.md").exists()
    assert (directory / "generate_checklist.md").exists()


def test_loading_records_a_content_hash() -> None:
    prompt = PromptLibrary().load("extract_claims")
    assert len(prompt.version) == 8
    assert "Allowed attributes" in prompt.text


def test_version_changes_when_the_file_changes(tmp_path: Path) -> None:
    directory = tmp_path / "prompts"
    directory.mkdir()
    file = directory / "probe.md"
    file.write_text("hello {{name}}", encoding="utf-8")

    first = PromptLibrary(directory).load("probe")
    file.write_text("hello {{name}} again", encoding="utf-8")
    second = PromptLibrary(directory).load("probe")

    assert first.version != second.version


def test_render_substitutes_values(tmp_path: Path) -> None:
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "probe.md").write_text("Hi {{name}}, at {{time}}s", encoding="utf-8")

    rendered = render(PromptLibrary(directory).load("probe"), name="mug", time=3)
    assert rendered == "Hi mug, at 3s"


def test_missing_value_is_an_error(tmp_path: Path) -> None:
    directory = tmp_path / "prompts"
    directory.mkdir()
    (directory / "probe.md").write_text("Hi {{name}}", encoding="utf-8")

    with pytest.raises(PromptError, match="missing values for name"):
        render(PromptLibrary(directory).load("probe"))


def test_missing_prompt_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="not found"):
        PromptLibrary(tmp_path).load("nope")
