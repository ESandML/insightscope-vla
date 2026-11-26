"""Input routing, shared by the CLI and the UI.

Speech and reference are independent axes. Keeping the decision here means the web UI
cannot drift from the command line: both build an :class:`InputPlan` and hand it to the
same pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SpeechSource = Literal["listen", "transcript", "audio", "none"]
ReferenceSource = Literal["none", "process", "spec"]
InputMode = Literal["listen", "transcript", "audio", "process", "spec", "hybrid"]


@dataclass(frozen=True, slots=True)
class InputPlan:
    """Where claims come from, and whether there is a reference to check them against."""

    speech: SpeechSource
    reference: ReferenceSource

    @property
    def is_hybrid(self) -> bool:
        return self.speech != "none" and self.reference != "none"

    @property
    def mode(self) -> InputMode:
        if self.is_hybrid:
            return "hybrid"
        if self.reference != "none":
            return self.reference
        if self.speech == "transcript":
            return "transcript"
        if self.speech == "audio":
            return "audio"
        return "listen"

    @property
    def needs_whisper(self) -> bool:
        return self.speech in ("listen", "audio")


def plan_for(
    *,
    transcript: bool = False,
    listen: bool = False,
    audio: bool = False,
    process: bool = False,
    spec: bool = False,
) -> InputPlan:
    """Build a plan from user intent.

    ``process`` and ``spec`` default to silence. ``listen`` overrides that default,
    which is what produces the hybrid modes. ``transcript``, ``listen`` and ``audio``
    are three ways to answer the same question and cannot be combined.
    """
    if sum((bool(transcript), bool(listen), bool(audio))) > 1:
        raise ValueError("choose one speech source: transcript, listen, or audio")

    reference: ReferenceSource = "process" if process else "spec" if spec else "none"

    if audio:
        speech: SpeechSource = "audio"
    elif transcript:
        speech = "transcript"
    elif listen or reference == "none":
        speech = "listen"
    else:
        speech = "none"

    return InputPlan(speech=speech, reference=reference)
