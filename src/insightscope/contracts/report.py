"""Report and critique contracts.

The critic is allowed to ask for a rewrite. It is not allowed to choose an arbitrary
graph node, invent a finding, or demand an assertion the evidence cannot support —
those are enforced by the enums here and by the deterministic gate that reads them.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IssueSeverity = Literal["blocker", "major", "minor"]


class IssueCode(StrEnum):
    MISSING_CITATION = "missing_citation"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    SEVERITY_MISMATCH = "severity_mismatch"
    UNCLEAR = "unclear"
    OTHER = "other"


class Issue(BaseModel):
    """One concrete complaint, pointing at something that already exists."""

    model_config = ConfigDict(extra="forbid")

    code: IssueCode
    severity: IssueSeverity
    target: Literal["extract", "synthesize"]
    ref: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=500)


class Critique(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["accept", "revise"]
    issues: list[Issue] = Field(default_factory=list)
    rationale: str = Field(default="", max_length=1000)


class ReportDraft(BaseModel):
    """Markdown plus the finding ids it actually cites. Both are validated in code."""

    model_config = ConfigDict(extra="forbid")

    markdown: str = Field(min_length=1)
    cited_finding_ids: list[str] = Field(default_factory=list)
