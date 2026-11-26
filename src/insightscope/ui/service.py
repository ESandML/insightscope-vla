"""UI run adapter: one request in, display-ready values out.

Everything that matters (routing, keyframes, graph, report) is shared with the CLI.
This module only translates UI values into a request and the result into strings and
file paths that Gradio components can render.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from insightscope.actions.db import history
from insightscope.clients.factory import ClientTriple, build_clients
from insightscope.config import ModelChoice, RunConfig, Settings
from insightscope.domain.checklist import ChecklistSpec
from insightscope.inputs import InputPlan
from insightscope.pipeline import (
    PipelineError,
    execute_run,
    prepare_run,
    resolve_transcript,
    spec_yaml,
)
from insightscope.telemetry.keyframes import video_duration

HISTORY_COLUMNS = ("run_id", "created_at", "status", "source_path", "n_findings", "n_annotated")


@dataclass(frozen=True, slots=True)
class UiRequest:
    clip: Path
    plan: InputPlan
    artifacts_dir: Path = Path("artifacts")
    db_path: Path = Path("audits.db")
    audio_path: Path | None = None
    transcript_path: Path | None = None
    spec: ChecklistSpec | None = None
    generated_spec: bool = False
    flag_omissions: bool = False
    client: str = "fake"
    cassette_path: Path | None = None
    whisper_model: str = "small.en"
    text_model: str | None = None
    vision_model: str | None = None
    base_url: str | None = None


@dataclass(frozen=True, slots=True)
class UiRunResult:
    run_id: str = ""
    status: str = "error"
    report_markdown: str = ""
    keyframes: tuple[tuple[str, str], ...] = ()
    flagged: tuple[str, ...] = ()
    assertions_json: str = ""
    spec_yaml: str = ""
    history: tuple[tuple[object, ...], ...] = ()
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def run_ui_audit(
    request: UiRequest,
    *,
    on_stage: Any | None = None,
    clients: ClientTriple | None = None,
) -> UiRunResult:
    """Run one audit for the UI, returning display values instead of raising."""
    try:
        triple = clients or build_clients(
            kind=request.client,
            text_model=request.text_model,
            vision_model=request.vision_model,
            base_url=request.base_url,
            replay=request.cassette_path,
        )

        bundle = resolve_transcript(
            plan=request.plan,
            clip=request.clip,
            duration_s=video_duration(request.clip),
            transcript_path=request.transcript_path,
            audio_path=request.audio_path,
            whisper_model=request.whisper_model,
        )
        config = RunConfig(
            checklist=request.spec,
            flag_omissions=request.flag_omissions,
            artifacts_dir=request.artifacts_dir,
            db_path=request.db_path,
            models=_model_choice(request),
        )
        prepared = prepare_run(
            clip=request.clip,
            config=config,
            plan=request.plan,
            bundle=bundle,
            generated_spec=request.generated_spec,
        )
        outcome = asyncio.run(
            execute_run(
                prepared,
                text_client=triple.text,
                vision_client=triple.vision,
                on_stage=on_stage,
            )
        )
    except (PipelineError, ValueError, OSError, RuntimeError) as exc:
        return UiRunResult(error=str(exc), history=_history_rows(request.db_path))
    except Exception as exc:
        return UiRunResult(
            error=f"{type(exc).__name__}: {exc}", history=_history_rows(request.db_path)
        )

    report = outcome.report
    actions = outcome.state.get("actions")
    flagged = tuple(actions.annotated) if actions is not None else ()

    assertions = {
        "claims": [item.model_dump(mode="json") for item in outcome.state.get("claims") or []],
        "observations": [
            item.model_dump(mode="json") for item in outcome.state.get("observations") or []
        ],
        "findings": [finding.model_dump(mode="json") for finding in report.findings],
    }

    return UiRunResult(
        run_id=prepared.run_id,
        status=report.status,
        report_markdown=report.markdown,
        keyframes=tuple(
            (keyframe.uri, f"{_timestamp(keyframe.span.t_start_s)} · {keyframe.reason}")
            for keyframe in prepared.evidence.keyframes
        ),
        flagged=flagged,
        assertions_json=json.dumps(assertions, indent=2),
        spec_yaml=spec_yaml(config.checklist) if config.checklist is not None else "",
        history=_history_rows(request.db_path),
    )


def generate_spec_text(
    description: str,
    *,
    client: str = "fake",
    cassette_path: Path | None = None,
    text_model: str | None = None,
    base_url: str | None = None,
) -> str:
    """Draft a spec and return editable YAML. Does not run an audit."""
    if not description.strip():
        raise ValueError("enter a process description first")

    triple = build_clients(
        kind=client,
        text_model=text_model,
        base_url=base_url,
        replay=cassette_path,
    )
    spec = asyncio.run(triple.generator.generate_checklist(description))
    return spec_yaml(spec)


def _model_choice(request: UiRequest) -> ModelChoice:
    if request.client in ("fake", "cassette"):
        return ModelChoice(text="fake", vision="fake")
    settings = Settings()
    return ModelChoice(
        text=request.text_model or settings.text_model,
        vision=request.vision_model or settings.vision_model,
    )


def _history_rows(db_path: Path) -> tuple[tuple[object, ...], ...]:
    rows = history(db_path, limit=20)
    return tuple(tuple(row.get(column) for column in HISTORY_COLUMNS) for row in rows)


def _timestamp(seconds: float) -> str:
    minutes, remainder = divmod(max(0.0, seconds), 60.0)
    return f"{int(minutes):02d}:{remainder:04.1f}"
