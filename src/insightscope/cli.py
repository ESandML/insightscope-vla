"""Command line entry point.

Two commands:

``insightscope keyframes CLIP``
    Run the real telemetry path and print what was selected, with the reason for each
    frame. This is the fastest way to tune motion thresholds on your own camera.

``insightscope audit CLIP``
    Run the whole graph. Until the Ollama client lands, extraction uses scripted
    clients, so this proves the wiring and produces a report; it does not interpret the
    clip yet.

Exit codes: 0 success, 1 the run escalated, 2 bad input.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from insightscope import __version__
from insightscope.clients.fake import FakeTextClient, FakeVisionClient
from insightscope.config import KeyframeConfig, RunConfig
from insightscope.domain.checklist import ChecklistError, load_checklist
from insightscope.domain.models import EvidenceManifest
from insightscope.graph.build import build_graph
from insightscope.telemetry.keyframes import (
    TelemetryError,
    select_keyframes,
    video_duration,
)
from insightscope.telemetry.transcript_source import (
    TranscriptBundle,
    TranscriptError,
    load_transcript,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "keyframes":
            return _keyframes_command(args)
        return _audit_command(args)
    except (TelemetryError, TranscriptError, ChecklistError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


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
        "--client",
        choices=["fake"],
        default="fake",
        help="fake = scripted, no model called (Ollama arrives in the next slice)",
    )
    _add_tuning_arguments(audit)

    return parser


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
    bundle = _transcript(args.transcript, duration)

    config = RunConfig(
        keyframes=_keyframe_config(args),
        checklist=load_checklist(args.checklist) if args.checklist else None,
        flag_omissions=bool(args.flag_omissions),
        artifacts_dir=args.artifacts_dir,
        db_path=args.db,
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

    graph = build_graph(
        text_client=FakeTextClient(),
        vision_client=FakeVisionClient(),
    )
    final = asyncio.run(graph.ainvoke({"run_id": run_id, "config": config, "evidence": evidence}))

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
    print("clients:   fake (no model called; Ollama lands in the next slice)")

    return 0 if report.status in ("complete", "complete_with_caveats") else 1


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
