"""Command line entry point.

Input routing has two independent axes:

* **Speech** — ``--transcript`` (file), ``--listen`` (clip audio), or ``--audio``
  (a separate recording). At most one. With no speech flag, audio is transcribed only
  when there is no spec reference.
* **Reference** — ``--spec`` loads a YAML audit spec; ``--process``/``--process-file``
  turns a plain-English description into one (saved for review). These are mutually
  exclusive with each other and never call Whisper on their own.

That yields four single modes (listen, transcript, process, spec), the ``--audio``
variant for silent videos, and four hybrids. All planning lives in
:mod:`insightscope.inputs`; execution lives in :mod:`insightscope.pipeline`.

``insightscope spec new "..." -o task.yaml`` drafts an audit spec: the model proposes,
you inspect and edit, then pass it back with ``--spec``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from insightscope import __version__
from insightscope.clients.base import ClientError
from insightscope.clients.cassettes import CassetteMiss
from insightscope.clients.factory import ClientTriple, build_clients
from insightscope.config import KeyframeConfig, ModelChoice, RunConfig, Settings
from insightscope.domain.checklist import (
    ChecklistError,
    ChecklistSpec,
    load_checklist,
    resolve_spec_path,
    save_spec_to_dir,
)
from insightscope.inputs import InputPlan, plan_for
from insightscope.pipeline import (
    PipelineError,
    execute_run,
    prepare_run,
    resolve_transcript,
)
from insightscope.telemetry.keyframes import TelemetryError, select_keyframes, video_duration
from insightscope.telemetry.transcript_source import (
    TranscriptBundle,
    TranscriptError,
    load_transcript,
)
from insightscope.telemetry.whisper import TranscriptionError, TranscriptionUnavailable


class CliError(RuntimeError):
    """An input or environment problem the user can fix."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "keyframes":
            return _keyframes_command(args)
        if args.command in ("spec", "checklist"):
            return _spec_new_command(args)
        return _audit_command(args)
    except (
        TelemetryError,
        TranscriptError,
        ChecklistError,
        TranscriptionError,
        TranscriptionUnavailable,
        PipelineError,
        CliError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except CassetteMiss as exc:
        print(f"error: cassette miss: {exc}", file=sys.stderr)
        return 1
    except ClientError as exc:
        print(f"error: model call failed: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="insightscope",
        description="Audit what a camera saw against what someone said or planned.",
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
    audit.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    audit.add_argument("--db", type=Path, default=Path("audits.db"))
    audit.add_argument(
        "--specs-dir",
        type=Path,
        default=None,
        help="directory holding audit specs (default: specs/, or INSIGHTSCOPE_SPECS_DIR)",
    )
    audit.add_argument(
        "--flag-omissions",
        action="store_true",
        help="report visible changes that were never mentioned (noisy)",
    )
    audit.add_argument(
        "--whisper-model",
        default="small.en",
        help="speech-to-text model for listen/audio modes",
    )

    # Speech source: at most one of a file, the clip's audio, or a separate recording.
    speech = audit.add_mutually_exclusive_group()
    speech.add_argument(
        "--transcript",
        type=Path,
        help=".json or .txt transcript; skips speech-to-text",
    )
    speech.add_argument(
        "--listen",
        action="store_true",
        help="transcribe the clip's audio even when --process/--spec is given",
    )
    speech.add_argument(
        "--audio",
        type=Path,
        metavar="FILE",
        help="separate voice recording (.wav/.mp3/.m4a) for a silent video",
    )

    # One reference source, or none.
    source = audit.add_mutually_exclusive_group()
    source.add_argument(
        "--process",
        metavar="TEXT",
        help="plain-English process description; generated spec is saved for review",
    )
    source.add_argument(
        "--process-file",
        type=Path,
        metavar="FILE",
        help="file containing a plain-English process description",
    )
    source.add_argument(
        "--spec",
        "--checklist",
        dest="spec",
        type=Path,
        metavar="FILE",
        help="YAML audit spec (--checklist is an alias)",
    )

    _add_client_arguments(audit)
    _add_tuning_arguments(audit)

    spec = sub.add_parser(
        "spec",
        aliases=["checklist"],
        help="draft audit specs for review (checklist is an alias)",
    )
    spec_sub = spec.add_subparsers(dest="spec_command", required=True)
    new = spec_sub.add_parser("new", help="draft an audit spec from a process description")
    new.add_argument("description", help="plain-English process description")
    new.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="file name inside specs/, e.g. make_tea.yaml",
    )
    new.add_argument(
        "--specs-dir",
        type=Path,
        default=None,
        help="directory to write the spec into (default: specs/)",
    )
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
    bundle = (
        load_transcript(args.transcript, duration_s=duration)
        if args.transcript
        else TranscriptBundle(utterances=(), mode="none")
    )

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
    specs_dir = _specs_dir(args)
    clients = _clients(args)
    plan = _plan(args)
    spec, generated = _resolve_spec(args, clients.generator, specs_dir)

    bundle = resolve_transcript(
        plan=plan,
        clip=clip,
        duration_s=video_duration(clip),
        transcript_path=args.transcript,
        audio_path=args.audio,
        whisper_model=args.whisper_model,
    )

    config = RunConfig(
        keyframes=_keyframe_config(args),
        checklist=spec,
        flag_omissions=bool(args.flag_omissions),
        artifacts_dir=args.artifacts_dir,
        db_path=args.db,
        specs_dir=specs_dir,
        models=_model_choice(args),
    )
    prepared = prepare_run(
        clip=clip,
        config=config,
        plan=plan,
        bundle=bundle,
        generated_spec=generated,
    )
    outcome = asyncio.run(
        execute_run(prepared, text_client=clients.text, vision_client=clients.vision)
    )

    if clients.cassette is not None:
        print(f"cassette:  {clients.cassette.save()}")

    report = outcome.report
    print(f"run:       {prepared.run_id}")
    print(f"input:     {_describe_mode(plan, args, bundle, spec, prepared.generated_spec_path)}")
    print(f"status:    {report.status}")
    print(f"keyframes: {len(prepared.evidence.keyframes)}")
    print(f"claims:    {len(outcome.state.get('claims') or [])}")
    print(f"findings:  {len(report.findings)}")
    print(f"report:    {outcome.report_path}")
    if prepared.spec_path is not None:
        print(f"spec file: {prepared.spec_path}")
    print(f"clients:   {_describe_clients(args)}")

    return 0 if report.status in ("complete", "complete_with_caveats") else 1


def _spec_new_command(args: argparse.Namespace) -> int:
    clients = _clients(args)
    specs_dir = _specs_dir(args)

    spec = asyncio.run(clients.generator.generate_checklist(args.description))
    path = save_spec_to_dir(spec, specs_dir, str(args.output))

    print(f"wrote {path}")
    print(f"name: {spec.name} | objects: {len(spec.expected_objects)} | steps: {len(spec.steps)}")
    print("review and edit it, then run:")
    print(f"  insightscope audit CLIP --spec {path.name} --specs-dir {specs_dir}")
    return 0


def _specs_dir(args: argparse.Namespace) -> Path:
    return Path(args.specs_dir) if args.specs_dir is not None else Settings().specs_dir


def _plan(args: argparse.Namespace) -> InputPlan:
    return plan_for(
        transcript=args.transcript is not None,
        listen=bool(args.listen),
        audio=args.audio is not None,
        process=args.process is not None or args.process_file is not None,
        spec=args.spec is not None,
    )


def _resolve_spec(
    args: argparse.Namespace, generator: Any, specs_dir: Path
) -> tuple[ChecklistSpec | None, bool]:
    """Return (spec, was_generated). Generation is the only model call here."""
    if args.spec is not None:
        return load_checklist(resolve_spec_path(args.spec, specs_dir)), False

    description: str | None = args.process
    if description is None and args.process_file is not None:
        path: Path = args.process_file
        if not path.exists():
            raise CliError(f"{path}: process file not found")
        description = path.read_text(encoding="utf-8").strip()
        if not description:
            raise CliError(f"{path}: process file is empty")

    if description is None:
        return None, False

    return asyncio.run(generator.generate_checklist(description)), True


def _describe_mode(
    plan: InputPlan,
    args: argparse.Namespace,
    bundle: TranscriptBundle,
    spec: ChecklistSpec | None,
    generated_path: Path | None,
) -> str:
    name = spec.name if spec is not None else "?"

    if plan.reference == "spec":
        reference = f"spec {name} ({args.spec})"
    elif plan.reference == "process":
        reference = f"process text → spec {name} ({generated_path})"
    else:
        reference = ""

    if plan.reference == "none":
        if plan.speech == "transcript":
            return f"transcript ({bundle.mode}, {len(bundle.utterances)} segments)"
        if plan.speech == "audio":
            return f"audio ({args.audio}, {len(bundle.utterances)} segments)"
        return f"listen (whisper {args.whisper_model}, {len(bundle.utterances)} segments)"

    if plan.speech == "none":
        return reference

    speech_label = "listen" if plan.speech == "listen" else plan.speech
    return f"hybrid ({speech_label} + {reference})"


def _clients(args: argparse.Namespace) -> ClientTriple:
    kind = "cassette" if args.replay is not None else args.client
    try:
        return build_clients(
            kind=kind,
            text_model=args.text_model,
            vision_model=args.vision_model,
            base_url=args.base_url,
            record=args.record,
            replay=args.replay,
        )
    except RuntimeError as exc:
        raise CliError(str(exc)) from exc


def _keyframe_config(args: argparse.Namespace) -> KeyframeConfig:
    defaults = KeyframeConfig()
    return KeyframeConfig(
        max_keyframes=args.max_keyframes or defaults.max_keyframes,
        analysis_fps=args.analysis_fps or defaults.analysis_fps,
        motion_threshold=args.motion_threshold or defaults.motion_threshold,
        max_frame_side=args.max_side or defaults.max_frame_side,
    )


def _model_choice(args: argparse.Namespace) -> ModelChoice:
    if args.client == "fake" or args.replay is not None:
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


def _timestamp(seconds: float) -> str:
    minutes, remainder = divmod(max(0.0, seconds), 60.0)
    return f"{int(minutes):02d}:{remainder:04.1f}"


if __name__ == "__main__":
    raise SystemExit(main())
