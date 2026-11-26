"""Extraction contracts.

Two shapes matter:

* ``ClaimBatch`` — what the speaker said, one item per claim, with the exact quote
  it came from. The quote is checked against the transcript in code, so a model
  cannot invent evidence.
* ``KeyframeAnalysis`` — what one picture shows. It may verify claims it was asked
  about, and it may propose which object the speaker was interacting with when the
  transcript said "this". It never decides whether those things conflict.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from insightscope.domain.ontology import Attribute, AttributeValue, coerce_value, normalize_action

Visibility = ("clear", "partial", "occluded")


class ClaimItem(BaseModel):
    """One factual claim extracted from one utterance."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1)
    attribute: Attribute
    action: str | None = None
    value: AttributeValue
    quote: str = Field(min_length=1)
    t_hint_s: float | None = Field(default=None, ge=0.0)

    @field_validator("action")
    @classmethod
    def _canonical_action(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        attribute = info.data.get("attribute")
        if not isinstance(attribute, Attribute) or attribute is not Attribute.ACTION_COMPLETED:
            raise ValueError("action is only valid for action_completed")
        return normalize_action(value)

    @model_validator(mode="after")
    def _canonical(self) -> ClaimItem:
        if self.attribute is Attribute.ACTION_COMPLETED and not self.action:
            raise ValueError("action is required when attribute is action_completed")
        object.__setattr__(self, "value", coerce_value(self.attribute, self.value))
        if not self.quote.strip():
            raise ValueError("quote must contain text")
        return self


class ClaimBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[ClaimItem] = Field(default_factory=list)


class VerifiedClaim(BaseModel):
    """The vision model's answer about one requested subject."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1)
    attribute: Attribute
    action: str | None = None
    value: AttributeValue
    visibility: str = Field(default="clear")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("action")
    @classmethod
    def _canonical_action(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        attribute = info.data.get("attribute")
        if not isinstance(attribute, Attribute) or attribute is not Attribute.ACTION_COMPLETED:
            raise ValueError("action is only valid for action_completed")
        return normalize_action(value)

    @model_validator(mode="after")
    def _canonical(self) -> VerifiedClaim:
        if self.attribute is Attribute.ACTION_COMPLETED and not self.action:
            raise ValueError("action is required when attribute is action_completed")
        object.__setattr__(self, "value", coerce_value(self.attribute, self.value))
        if self.visibility not in Visibility:
            raise ValueError(f"visibility must be one of {Visibility}, got {self.visibility!r}")
        return self


class ObservedChange(BaseModel):
    """Something visibly changed, used only for optional omission findings."""

    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=1)
    description: str = Field(default="", max_length=200)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class KeyframeAnalysis(BaseModel):
    """Everything one keyframe is asked to report."""

    model_config = ConfigDict(extra="forbid")

    keyframe_id: str = Field(min_length=1)
    verified: list[VerifiedClaim] = Field(default_factory=list)
    interacted_object: str | None = None
    interaction_note: str = Field(default="", max_length=200)
    observed_changes: list[ObservedChange] = Field(default_factory=list)
