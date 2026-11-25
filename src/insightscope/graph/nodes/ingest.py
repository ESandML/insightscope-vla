"""Normalise the evidence bundle before anything expensive happens.

Sorting and de-duplicating keyframes here means every later node can assume a stable
order, which is what makes the report and the tests reproducible. The cap is applied
here too, so a 10-minute clip cannot accidentally send 300 frames to a local VLM.
"""

from __future__ import annotations

from insightscope.graph.nodes._common import NodeUpdate
from insightscope.graph.state import AuditState


def ingest(state: AuditState) -> NodeUpdate:
    evidence = state["evidence"]
    config = state["config"]

    ordered = sorted(evidence.keyframes, key=lambda kf: (kf.span.t_start_s, kf.keyframe_id))
    unique = []
    seen: set[str] = set()
    for keyframe in ordered:
        if keyframe.keyframe_id in seen:
            continue
        seen.add(keyframe.keyframe_id)
        unique.append(keyframe)

    capped = tuple(unique[: config.keyframes.max_keyframes])
    notes = list(evidence.notes)
    if evidence.transcript_mode == "text":
        notes.append("transcript has no timestamps: alignment is degraded")
    if not evidence.utterances:
        notes.append("no transcript: only what the camera saw is available")
    if len(unique) > len(capped):
        notes.append(f"keyframes capped at {config.keyframes.max_keyframes}")
    notes = list(dict.fromkeys(notes))

    return {
        "evidence": evidence.model_copy(update={"keyframes": capped, "notes": tuple(notes)}),
        "run_id": state.get("run_id") or f"run-{evidence.bundle_id}",
        "cycle": state.get("cycle", 0),
        "status": "extracting",
        "trace": ["ingest"],
    }
