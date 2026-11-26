"""Command line entry point.

``insightscope keyframes CLIP``
    Run telemetry only and print what was selected, with the reason for each frame.

``insightscope audit CLIP``
    Run the whole graph. ``--client fake`` uses scripted responses (offline);
    ``--client ollama`` calls a local model server.

``insightscope checklist new "..." -o desk.yaml``
    Ask a model to draft a checklist, write it to YAML, and stop. You inspect and edit
    it before using it — the model proposes, you approve, code executes.

Exit codes: 0 success, 1 the run escalated, 2 bad input or missing dependency.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from insightscope import __version__
from insightscope.clients.base import ClientError
from insightscope.clients.cassettes import Cassette, CassettePlayer, CassetteRecorder
from insightscope.clients.fake import FakeTextClient, FakeVisionClient
from insightscope.config import KeyframeConfig, ModelChoice, RunConfig, Settings
from insightscope.domain.checklist import ChecklistError, dump_checklist, load_checklist
from insightscope.domain.models import EvidenceManifest
from insightscope.graph.build import build_graph
from insightscope.telemetry.keyframes import TelemetryError, select_keyframes, video_duration
from insightscope.telemetry.transcript_source import (
    TranscriptBundle,
    TranscriptError,
    load_transcript,
)
from insightscope.telemetry.whisper import (
    TranscriptionError,
    TranscriptionUnavailable,
    transcribe,
)


class CliError(RuntimeError):
    """An input or environment problem the user can fix."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "keyframes":
            return _keyframes_command(args)
        if args.command == "checklist":
            return _checklist_new_command(args)
        return _audit_command(args)
    except (
        TelemetryError,
        TranscriptError,
        ChecklistError,
        TranscriptionError,
        TranscriptionUnavailable,
        CliError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ClientError as exc:
        print(f"error: model call failed: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="insightscope",
        description="Audit what a camera saw against what someone said.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    keyframes = sub.add_parser("keyframes", help="select and save keyframes from a clip")
    keyframes.add_argument("clip", type=Path, help="video file")
    keyframes.add_argument("--out", type=Path, default=Path("artifacts/keyframes"))
    keyframes.add_argument("--transcript", type=Path, help=".json or .txt transcript")
    _add_tuning_arguments(keyframes)

    audit = sub.add_parser("audit", help="run the audit graph over a clip")
    audit.add_argument("clip", type=Path, help="video file")
    audit.add_argument("--transcript", type=Path, help=".json or .txt transcript")
    audit.add_argument("--checklist", type=Path, help="optional YAML checklist")
    audit.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    audit.add_argument("--db", type=Path, default=Path("audits.db"))
    audit.add_argument(
        "--flag-omissions",
        action="store_true",
        help="report visible changes that were never mentioned (noisy)",
    )
    audit.add_argument(
        "--whisper-model",
        default="small.en",
        help="speech-to-text model when --transcript is omitted and --client ollama",
    )
    _add_client_arguments(audit)
    _add_tuning_arguments(audit)

    checklist = sub.add_parser("checklist", help="draft checklists for review")
    checklist_sub = checklist.add_subparsers(dest="checklist_command", required=True)
    new = checklist_sub.add_parser("new", help="draft a checklist from a description")
    new.add_argument("description", help="plain-English task description")
    new.add_argument("-o", "--output", type=Path, required=True, help="YAML file to write")
    _add_client_arguments(new)

    return parser


def _add_client_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--client",
        choices=["fake", "ollama"],
        default="fake",
        help="fake = scripted, offline (default); ollama = local model server",
    )
    parser.add_argument("--text-model", default=None)
    parser.add_argument("--vision-model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument(
        "--record",
        type=Path,
        default=None,
        help="save model responses to this cassette file",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        default=None,
        help="serve model responses from this cassette file instead of calling a model",
    )


def _add_tuning_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-keyframes", type=int, default=None)
    parser.add_argument("--analysis-fps", type=float, default=None)
    parser.add_argument("--motion-threshold", type=float, default=None)
    parser.add_argument("--max-side", type=int, default=None, help="resize longest side")


def _keyframes_command(args: argparse.Namespace) -> int:
    clip: Path = args.clip
    duration = video_duration(clip)
    bundle = _transcript(args.transcript, duration)

    refs = select_keyframes(
        video_path=clip,
        out_dir=args.out,
        config=_keyframe_config(args),
        utterances=bundle.utterances,
    )

    print(f"selected {len(refs)} keyframe(s) from {clip} ({args.out})")
    print(f"{'#':>3}  {'time':>7}  {'reason':<11}  {'size':>9}  id")
    for number, ref in enumerate(refs, start=1):
        print(
            f"{number:>3}  {_timestamp(ref.span.t_start_s):>7}  "
            f"{ref.reason:<11}  {ref.width:>4}x{ref.height:<4}  {ref.keyframe_id}"
        )
    return 0


def _audit_command(args: argparse.Namespace) -> int:
    clip: Path = args.clip
    duration = video_duration(clip)

    text_client, vision_client, _generator = _clients(args)
    bundle = _transcript_for_audit(args, clip, duration)

    config = RunConfig(
        keyframes=_keyframe_config(args),
        checklist=load_checklist(args.checklist) if args.checklist else None,
        flag_omissions=bool(args.flag_omissions),
        artifacts_dir=args.artifacts_dir,
        db_path=args.db,
        models=_model_choice(args),
    )
    run_id = _run_id(clip, config)
    run_dir = config.artifacts_dir / run_id

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

    graph = build_graph(text_client=text_client, vision_client=vision_client)
    final = asyncio.run(graph.ainvoke({"run_id": run_id, "config": config, "evidence": evidence}))

    if args.record is not None and isinstance(text_client, CassetteRecorder):
        saved = text_client.cassette.save()
        print(f"cassette:  {saved}")

    report = final.get("report")
    if report is None:
        print("error: the graph produced no report", file=sys.stderr)
        return 1

    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.md"
    report_path.write_text(report.markdown, encoding="utf-8")

    print(f"run:       {run_id}")
    print(f"status:    {report.status}")
    print(f"keyframes: {len(keyframes)}")
    print(f"claims:    {len(final.get('claims') or [])}")
    print(f"findings:  {len(report.findings)}")
    print(f"report:    {report_path}")
    if config.checklist is not None:
        print(f"checklist: {config.checklist.name}")
    print(f"clients:   {_describe_clients(args)}")

    return 0 if report.status in ("complete", "complete_with_caveats") else 1


def _checklist_new_command(args: argparse.Namespace) -> int:
    _text, _vision, generator = _clients(args)

    spec = asyncio.run(generator.generate_checklist(args.description))
    path = dump_checklist(spec, args.output)

    print(f"wrote {path}")
    print(f"name: {spec.name} | objects: {len(spec.expected_objects)} | steps: {len(spec.steps)}")
    print("review and edit it, then run:")
    print(f"  insightscope audit CLIP --checklist {path}")
    return 0


def _clients(args: argparse.Namespace) -> tuple[Any, Any, Any]:
    """Resolve the client triple: (text, vision, checklist generator)."""
    if args.replay is not None:
        player = CassettePlayer(Cassette.load(args.replay))
        return player, player, player

    if args.client == "fake":
        fake = FakeTextClient()
        text: Any = fake
        vision: Any = FakeVisionClient()
        generator: Any = fake
    else:
        settings = Settings()
        overrides: dict[str, Any] = {}
        if args.text_model:
            overrides["text_model"] = args.text_model
        if args.vision_model:
            overrides["vision_model"] = args.vision_model
        if args.base_url:
            overrides["llm_base_url"] = args.base_url
        if overrides:
            settings = settings.model_copy(update=overrides)

        try:
            from insightscope.clients.openai_compat import OllamaClients
        except ImportError as exc:  # pragma: no cover - module has no import-time deps
            raise CliError(f"could not load the Ollama client: {exc}") from exc

        try:
            ollama = OllamaClients(settings=settings)
        except RuntimeError as exc:
            raise CliError(str(exc)) from exc
        text, vision, generator = ollama, ollama, ollama

    if args.record is None:
        return text, vision, generator

    cassette = Cassette(Path(args.record))
    return (
        CassetteRecorder(text, cassette),
        CassetteRecorder(vision, cassette),
        CassetteRecorder(generator, cassette),
    )


def _transcript_for_audit(
    args: argparse.Namespace, clip: Path, duration: float
) -> TranscriptBundle:
    if args.transcript is not None:
        return load_transcript(args.transcript, duration_s=duration)
    if args.replay is not None:
        raise CliError("--replay needs the transcript the cassette was recorded with")
    if args.client == "fake":
        return TranscriptBundle(utterances=(), mode="none")
    return transcribe(clip, model_size=args.whisper_model)


def _transcript(path: Path | None, duration_s: float) -> TranscriptBundle:
    if path is None:
        return TranscriptBundle(utterances=(), mode="none")
    return load_transcript(path, duration_s=duration_s)


def _keyframe_config(args: argparse.Namespace) -> KeyframeConfig:
    defaults = KeyframeConfig()
    return KeyframeConfig(
        max_keyframes=args.max_keyframes or defaults.max_keyframes,
        analysis_fps=args.analysis_fps or defaults.analysis_fps,
        motion_threshold=args.motion_threshold or defaults.motion_threshold,
        max_frame_side=args.max_side or defaults.max_frame_side,
    )


def _model_choice(args: argparse.Namespace) -> ModelChoice:
    if args.client == "fake":
        return ModelChoice(text="fake", vision="fake")
    settings = Settings()
    return ModelChoice(
        text=args.text_model or settings.text_model,
        vision=args.vision_model or settings.vision_model,
    )


def _describe_clients(args: argparse.Namespace) -> str:
    if args.replay is not None:
        return f"cassette replay ({args.replay})"
    if args.client == "fake":
        return "fake (scripted, no model called)"
    target = args.base_url or Settings().llm_base_url
    return f"ollama at {target}"


def _run_id(clip: Path, config: RunConfig) -> str:
    """Stable for the same clip and settings, so reruns overwrite rather than pile up."""
    return f"run-{_slug(clip.stem)}-{_file_digest(clip)[:8]}-{_config_fingerprint(config)}"


def _config_fingerprint(config: RunConfig) -> str:
    payload = {
        "checklist": config.checklist.name if config.checklist else None,
        "flag_omissions": config.flag_omissions,
        "max_keyframes": config.keyframes.max_keyframes,
        "tolerance_s": config.alignment.tolerance_s,
        "text_model": config.models.text,
        "vision_model": config.models.vision,
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


def _timestamp(seconds: float) -> str:
    minutes, remainder = divmod(max(0.0, seconds), 60.0)
    return f"{int(minutes):02d}:{remainder:04.1f}"


if __name__ == "__main__":
    raise SystemExit(main())
