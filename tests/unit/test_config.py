"""RunConfig defaults, freezing, and YAML loading with a checklist reference."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from insightscope.config import RunConfig, Settings, config_from_yaml

CHECKLIST = Path(__file__).parent.parent / "fixtures" / "checklists" / "desk.yaml"


def test_defaults_are_open_ended() -> None:
    config = RunConfig()
    assert config.checklist is None
    assert config.flag_omissions is False
    assert config.alignment.tolerance_s == 3.0
    assert config.keyframes.max_keyframes == 12


def test_symmetric_window_by_default() -> None:
    assert RunConfig().alignment.window() == (3.0, 3.0)


def test_asymmetric_window_for_trailing_narration() -> None:
    from insightscope.config import AlignmentConfig

    assert AlignmentConfig(before_s=1.0).window() == (1.0, 3.0)


def test_config_is_frozen() -> None:
    config = RunConfig()
    with pytest.raises(ValidationError):
        config.flag_omissions = True  # type: ignore[misc]


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RunConfig(patient_id="nope")  # type: ignore[call-arg]


def test_yaml_loads_checklist_relative_to_the_config(tmp_path: Path) -> None:
    checklist = tmp_path / "desk.yaml"
    checklist.write_text(CHECKLIST.read_text(encoding="utf-8"), encoding="utf-8")
    run_file = tmp_path / "run.yaml"
    run_file.write_text("checklist: desk.yaml\nflag_omissions: true\n", encoding="utf-8")

    config = config_from_yaml(run_file)
    assert config.checklist is not None
    assert config.checklist.name == "pack_the_desk"
    assert config.flag_omissions is True


def test_yaml_without_checklist_stays_open_ended(tmp_path: Path) -> None:
    run_file = tmp_path / "run.yaml"
    run_file.write_text("flag_omissions: false\n", encoding="utf-8")
    assert config_from_yaml(run_file).checklist is None


def test_env_settings_use_the_insightscope_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSIGHTSCOPE_LLM_BASE_URL", "http://example.test/v1")
    monkeypatch.setenv("INSIGHTSCOPE_TEXT_MODEL", "tiny")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.llm_base_url == "http://example.test/v1"
    assert settings.text_model == "tiny"
