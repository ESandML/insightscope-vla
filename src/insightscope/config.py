"""Every knob in one frozen object.

Frozen matters: routing reads these values, so a node that wants to raise its own
budget should be a code change under review, not a field assignment at runtime.

Connection details (base URL, key) live in ``Settings`` instead, because they come
from the environment and have nothing to do with audit behaviour.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from insightscope.domain.checklist import ChecklistSpec, load_checklist


class ModelChoice(BaseModel):
    """Which local model does which job."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = "llama3.1:8b"
    vision: str = "llama3.2-vision"


class AlignmentConfig(BaseModel):
    """How far apart a claim and an observation may sit and still be compared.

    Symmetric by default. Rules may use the asymmetric window, because people
    usually narrate an action after doing it rather than before.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tolerance_s: float = Field(default=3.0, gt=0.0)
    before_s: float | None = Field(default=None, ge=0.0)
    after_s: float | None = Field(default=None, ge=0.0)

    def window(self) -> tuple[float, float]:
        before = self.tolerance_s if self.before_s is None else self.before_s
        after = self.tolerance_s if self.after_s is None else self.after_s
        return before, after


class LoopConfig(BaseModel):
    """Retry limits. The graph may not exceed these, whatever a critic asks for."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_repair_cycles: int = Field(default=2, ge=0)
    max_node_attempts: int = Field(default=3, ge=1)
    deadline_s: float = Field(default=900.0, gt=0.0)


class KeyframeConfig(BaseModel):
    """Motion sampling: how many frames we look at, and how we choose them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_keyframes: int = Field(default=12, ge=1)
    analysis_fps: float = Field(default=4.0, gt=0.0)
    motion_threshold: float = Field(default=4.0, gt=0.0)
    cooldown_s: float = Field(default=1.5, ge=0.0)
    anchor_every_s: float = Field(default=10.0, gt=0.0)
    snap_before_s: float = Field(default=0.5, ge=0.0)
    snap_after_s: float = Field(default=1.0, ge=0.0)
    max_frame_side: int = Field(default=1024, ge=64)


class RunConfig(BaseModel):
    """Everything an individual audit run needs, except the media itself."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    keyframes: KeyframeConfig = Field(default_factory=KeyframeConfig)
    alignment: AlignmentConfig = Field(default_factory=AlignmentConfig)
    loop: LoopConfig = Field(default_factory=LoopConfig)
    models: ModelChoice = Field(default_factory=ModelChoice)

    # Local model servers (Ollama) serialise work; 2 is a safe edge default.
    max_concurrency: int = Field(default=2, ge=1)

    # Where run outputs go. Both are gitignored and safe to delete.
    artifacts_dir: Path = Path("artifacts")
    db_path: Path = Path("audits.db")

    # Open-ended by default. Supplying a checklist enables the step rules only.
    checklist: ChecklistSpec | None = None

    # Off by default: casual footage has too much background motion to flag it all.
    flag_omissions: bool = False


class Settings(BaseSettings):
    """Environment-driven connection settings. Read ``.env`` if present."""

    model_config = SettingsConfigDict(
        env_prefix="insightscope_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    vision_model: str = "llama3.2-vision"
    text_model: str = "llama3.1:8b"
    llm_timeout_s: float = 120.0


def config_from_yaml(path: str | Path) -> RunConfig:
    """Load a run config from YAML, resolving a ``checklist:`` path relative to it.

    Kept deliberately small: the YAML mirrors :class:`RunConfig`, plus an optional
    ``checklist: ./coffee.yaml`` line so a run is reproducible from one file.
    """
    import yaml

    source = Path(path)
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: expected a mapping at the top level")

    checklist_ref = raw.pop("checklist", None)
    checklist: ChecklistSpec | None = None
    if isinstance(checklist_ref, str):
        checklist = load_checklist(source.parent / checklist_ref)
    elif checklist_ref is not None:
        checklist = ChecklistSpec.model_validate(checklist_ref)

    return RunConfig.model_validate({**raw, "checklist": checklist})
