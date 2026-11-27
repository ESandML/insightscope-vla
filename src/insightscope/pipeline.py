"""The single execution path shared by the CLI and the UI.

Preparation (probe, keyframes, evidence) is synchronous and can be shown as a step.
Execution streams graph state so callers can render progress, then writes report.md.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from insightscope.config import RunConfig
from insightscope.domain.checklist import ChecklistSpec, dump_checklist, save_spec_to_dir
from insightscope.domain.models import AuditReport, EvidenceManifest
from insightscope.graph.build import build_graph
from insightscope.inputs import InputPlan
from insightscope.telemetry.keyframes import select_keyframes, video_duration
from insightscope.telemetry.transcript_source import (
    TranscriptBundle,
    load_transcript,
)
from insightscope.telemetry.whisper import has_audio_stream, transcribe


class PipelineError(RuntimeError):
    """A run cannot start or finish, for a reason the user can act on."""


@dataclass(frozen=True, slots=True)
class PreparedRun:
    run_id: str
    run_dir: Path
    config: RunConfig
    evidence: EvidenceManifest
    plan: InputPlan
    generated_spec_path: Path | None = None
    spec_path: Path | None = None


@dataclass(frozen=True, slots=True)
class AuditOutcome:
    prepared: PreparedRun
    report: AuditReport
    report_path: Path
    state: Mapping[str, Any]


def resolve_transcript(
    *,
    plan: InputPlan,
    clip: Path,
    duration_s: float,
    transcript_path: Path | None = None,
    audio_path: Path | None = None,
    whisper_model: str = "small.en",
) -> TranscriptBundle:
    """Turn the plan's speech source into utterances, or explain why it cannot."""
    if plan.speech == "transcript":
        if transcript_path is None:
            raise PipelineError("transcript mode needs a transcript file")
        return load_transcript(transcript_path, duration_s=duration_s)

    if plan.speech == "audio":
        if audio_path is None or not Path(audio_path).exists():
            raise PipelineError(f"{audio_path}: audio file not found")
        return transcribe(audio_path, model_size=whisper_model)

    if plan.speech == "listen":
        if not has_audio_stream(clip):
            raise PipelineError(
                "video has no audio track; pass --audio, --transcript, or a "
                "--spec/--process (add --listen only when the clip has sound)"
            )
        return transcribe(clip, model_size=whisper_model)

    return TranscriptBundle(utterances=(), mode="none")


def prepare_run(
    *,
    clip: Path,
    config: RunConfig,
    plan: InputPlan,
    bundle: TranscriptBundle,
    generated_spec: bool = False,
) -> PreparedRun:
    """Probe the clip, pick keyframes, and lay out the run directory."""
    duration = video_duration(clip)
    run_id = make_run_id(clip, config, plan=plan, bundle=bundle)
    run_dir = config.artifacts_dir / run_id

    generated_path: Path | None = None
    spec_path: Path | None = None
    if generated_spec and config.checklist is not None:
        generated_path = dump_checklist(config.checklist, run_dir / "generated_spec.yaml")
        # Also keep the canonical copy where the user expects to inspect it.
        spec_path = save_spec_to_dir(config.checklist, config.specs_dir)

    keyframes = select_keyframes(
        video_path=clip,
        out_dir=run_dir / "keyframes",
        config=config.keyframes,
        utterances=bundle.utterances,
    )
    evidence = EvidenceManifest(
        bundle_id=f"{_slug(clip.stem)}-{_file_digest(clip)[:8]}",
        source_path=str(clip),
        duration_s=duration,
        keyframes=keyframes,
        utterances=bundle.utterances,
        transcript_mode=bundle.mode,
    )
    return PreparedRun(
        run_id=run_id,
        run_dir=run_dir,
        config=config,
        evidence=evidence,
        plan=plan,
        generated_spec_path=generated_path,
        spec_path=spec_path,
    )


async def execute_run(
    prepared: PreparedRun,
    *,
    text_client: Any,
    vision_client: Any,
    on_stage: Callable[[str], None] | None = None,
) -> AuditOutcome:
    """Run the graph, streaming stage names, then write report.md."""
    graph = build_graph(text_client=text_client, vision_client=vision_client)
    initial = {
        "run_id": prepared.run_id,
        "config": prepared.config,
        "evidence": prepared.evidence,
    }

    final: Mapping[str, Any] | None = None
    async for snapshot in graph.astream(initial, stream_mode="values"):
        final = snapshot
        if on_stage is not None:
            trace = snapshot.get("trace") or []
            on_stage(trace[-1] if trace else "start")

    if final is None:
        raise PipelineError("the graph produced no state")
    report = final.get("report")
    if report is None:
        raise PipelineError("the graph produced no report")

    prepared.run_dir.mkdir(parents=True, exist_ok=True)
    report_path = prepared.run_dir / "report.md"
    report_path.write_text(report.markdown, encoding="utf-8")

    return AuditOutcome(
        prepared=prepared,
        report=report,
        report_path=report_path,
        state=final,
    )


def make_run_id(clip: Path, config: RunConfig, *, plan: InputPlan, bundle: TranscriptBundle) -> str:
    """Stable per (clip, settings, input plan, transcript content)."""
    return (
        f"run-{_slug(clip.stem)}-{_file_digest(clip)[:8]}"
        f"-{_config_fingerprint(config, plan=plan, bundle=bundle)}"
    )


def spec_yaml(spec: ChecklistSpec) -> str:
    """The spec as editable YAML, for previews and the generated-spec file."""
    import yaml

    return yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True)


def _config_fingerprint(config: RunConfig, *, plan: InputPlan, bundle: TranscriptBundle) -> str:
    payload = {
        "checklist": config.checklist.name if config.checklist else None,
        "flag_omissions": config.flag_omissions,
        "max_keyframes": config.keyframes.max_keyframes,
        "tolerance_s": config.alignment.tolerance_s,
        "text_model": config.models.text,
        "vision_model": config.models.vision,
        "input": {
            "mode": plan.mode,
            "speech": plan.speech,
            "reference": plan.reference,
        },
        "transcript": [utterance.utterance_id for utterance in bundle.utterances],
    }
    encoded = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()[:6]


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slug(value: str) -> str:
    cleaned = "".join(character if character.isalnum() else "-" for character in value.lower())
    return "-".join(part for part in cleaned.split("-") if part)[:24] or "clip"
