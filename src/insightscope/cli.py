"""Command line entry point.

Input routing for ``audit`` has two independent axes:

* **Speech** — ``--transcript`` (file) or the clip's audio via faster-whisper
  (``--listen``). With no flags, audio is transcribed only when there is no spec.
  ``--listen`` forces transcription even alongside ``--process``/``--spec``.
* **Reference** — ``--spec`` loads a YAML audit spec; ``--process``/``--process-file``
  turns a plain-English description into one (saved for review). These are mutually
  exclusive with each other and never call Whisper on their own.

That yields four single modes (listen, transcript, process, spec) and four hybrids
(audio+process, audio+spec, transcript+process, transcript+spec).

``insightscope spec new "..." -o task.yaml`` drafts an audit spec: the model proposes,
you inspect and edit, then pass it back with ``--spec``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from insightscope import __version__
from insightscope.clients.base import ClientError
from insightscope.clients.cassettes import Cassette, CassetteMiss, CassettePlayer, CassetteRecorder
from insightscope.clients.fake import FakeTextClient, FakeVisionClient
from insightscope.config import KeyframeConfig, ModelChoice, RunConfig, Settings
from insightscope.domain.checklist import (
    ChecklistError,
    ChecklistSpec,
    dump_checklist,
    load_checklist,
)
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

InputMode = Literal["listen", "transcript", "process", "spec", "hybrid"]
SpeechSource = Literal["listen", "transcript", "none"]
ReferenceSource = Literal["none", "process", "spec"]


@dataclass(frozen=True, slots=True)
class InputPlan:
    """Speech source and reference source, decided independently.

    Speech defaults to silence when a spec reference is present, and to Whisper
    otherwise. ``--listen`` overrides the default, which is what makes the four hybrid
    combinations (audio+process, audio+spec, transcript+process, transcript+spec) work.
    """

    speech: SpeechSource
    reference: ReferenceSource

    @property
    def is_hybrid(self) -> bool:
        return self.speech != "none" and self.reference != "none"


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
        "--flag-omissions",
        action="store_true",
        help="report visible changes that were never mentioned (noisy)",
    )
    audit.add_argument(
        "--whisper-model",
        default="small.en",
        help="speech-to-text model for listen mode",
    )

    # Speech source: a file, or the clip's audio. At most one.
    speech = audit.add_mutually_exclusive_group()
    speech.add_argument(
        "--transcript",
        type=Path,
        help=".json or .txt transcript; skips speech-to-text",
    )
    speech.add_argument(
        "--listen",
        action="store_true",
        help="transcribe the audio even when --process/--spec is given (hybrid run)",
    )

    # One reference source, or none. Transcript is orthogonal: it changes where the
    # claims come from, not what the spec expects.
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
    duration = video_duration(clip)

    text_client, vision_client, generator = _clients(args)
    plan = _input_plan(args)
    spec, generated = _resolve_spec(args, generator)
    bundle = _transcript_for_audit(args, clip, duration, plan)

    config = RunConfig(
        keyframes=_keyframe_config(args),
        checklist=spec,
        flag_omissions=bool(args.flag_omissions),
        artifacts_dir=args.artifacts_dir,
        db_path=args.db,
        models=_model_choice(args),
    )
    run_id = _run_id(clip, config, plan=plan, bundle=bundle)
    run_dir = config.artifacts_dir / run_id

    generated_path: Path | None = None
    if generated and spec is not None:
        generated_path = dump_checklist(spec, run_dir / "generated_spec.yaml")

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
        print(f"cassette:  {text_client.cassette.save()}")

    report = final.get("report")
    if report is None:
        print("error: the graph produced no report", file=sys.stderr)
        return 1

    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "report.md"
    report_path.write_text(report.markdown, encoding="utf-8")

    print(f"run:       {run_id}")
    print(f"input:     {_describe_mode(plan, args, bundle, spec, generated_path)}")
    print(f"status:    {report.status}")
    print(f"keyframes: {len(keyframes)}")
    print(f"claims:    {len(final.get('claims') or [])}")
    print(f"findings:  {len(report.findings)}")
    print(f"report:    {report_path}")
    print(f"clients:   {_describe_clients(args)}")

    return 0 if report.status in ("complete", "complete_with_caveats") else 1


def _spec_new_command(args: argparse.Namespace) -> int:
    _text, _vision, generator = _clients(args)

    spec = asyncio.run(generator.generate_checklist(args.description))
    path = dump_checklist(spec, args.output)

    print(f"wrote {path}")
    print(f"name: {spec.name} | objects: {len(spec.expected_objects)} | steps: {len(spec.steps)}")
    print("review and edit it, then run:")
    print(f"  insightscope audit CLIP --spec {path}")
    return 0


def _input_plan(args: argparse.Namespace) -> InputPlan:
    """Decide speech and reference independently, then report the combination."""
    if args.process is not None or args.process_file is not None:
        reference: ReferenceSource = "process"
    elif args.spec is not None:
        reference = "spec"
    else:
        reference = "none"

    if args.transcript is not None:
        speech: SpeechSource = "transcript"
    elif args.listen or reference == "none":
        speech = "listen"
    else:
        speech = "none"

    return InputPlan(speech=speech, reference=reference)


def _input_mode(plan: InputPlan) -> InputMode:
    if plan.is_hybrid:
        return "hybrid"
    if plan.reference != "none":
        return plan.reference
    return "transcript" if plan.speech == "transcript" else "listen"


def _resolve_spec(args: argparse.Namespace, generator: Any) -> tuple[ChecklistSpec | None, bool]:
    """Return (spec, was_generated). Generation is the only model call here."""
    if args.spec is not None:
        return load_checklist(args.spec), False

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


def _transcript_for_audit(
    args: argparse.Namespace, clip: Path, duration: float, plan: InputPlan
) -> TranscriptBundle:
    if plan.speech == "transcript":
        return load_transcript(args.transcript, duration_s=duration)
    if plan.speech == "listen":
        return transcribe(clip, model_size=args.whisper_model)
    return TranscriptBundle(utterances=(), mode="none")


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
        return f"listen (whisper {args.whisper_model}, {len(bundle.utterances)} segments)"

    if plan.speech == "none":
        return reference

    speech_label = "listen" if plan.speech == "listen" else "transcript"
    return f"hybrid ({speech_label} + {reference})"


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


def _run_id(clip: Path, config: RunConfig, *, plan: InputPlan, bundle: TranscriptBundle) -> str:
    """Stable per (clip, settings, input plan, transcript content)."""
    return (
        f"run-{_slug(clip.stem)}-{_file_digest(clip)[:8]}"
        f"-{_config_fingerprint(config, plan=plan, bundle=bundle)}"
    )


def _config_fingerprint(config: RunConfig, *, plan: InputPlan, bundle: TranscriptBundle) -> str:
    payload = {
        "checklist": config.checklist.name if config.checklist else None,
        "flag_omissions": config.flag_omissions,
        "max_keyframes": config.keyframes.max_keyframes,
        "tolerance_s": config.alignment.tolerance_s,
        "text_model": config.models.text,
        "vision_model": config.models.vision,
        "input": {
            "mode": _input_mode(plan),
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


def _timestamp(seconds: float) -> str:
    minutes, remainder = divmod(max(0.0, seconds), 60.0)
    return f"{int(minutes):02d}:{remainder:04.1f}"


if __name__ == "__main__":
    raise SystemExit(main())
