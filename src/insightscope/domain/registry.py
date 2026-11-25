"""The per-run subject list, built from what was said, what was seen, and the checklist.

This is the bridge between the two modalities. Because it is built by code from
already-canonical ids, "the mug" in the transcript and "coffee mug" in a checklist
land on the same entry, and anything that appears on only one side is explicitly
marked as such.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from insightscope.domain.checklist import ChecklistSpec
from insightscope.domain.models import Assertion, SubjectRef


class SubjectRegistry(BaseModel):
    """Subjects named by the transcript, by the camera, or by a checklist."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    refs: dict[str, SubjectRef] = Field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        said: Sequence[Assertion] = (),
        seen: Sequence[Assertion] = (),
        checklist: ChecklistSpec | None = None,
    ) -> SubjectRegistry:
        refs: dict[str, SubjectRef] = {}

        def touch(
            subject_id: str,
            *,
            is_said: bool = False,
            is_seen: bool = False,
            expected: bool = False,
        ) -> None:
            current = refs.get(subject_id)
            refs[subject_id] = SubjectRef(
                subject_id=subject_id,
                said=is_said or (current.said if current else False),
                seen=is_seen or (current.seen if current else False),
                expected=expected or (current.expected if current else False),
            )

        if checklist is not None:
            for name in checklist.expected_objects:
                touch(name, expected=True)
            for step in checklist.steps:
                touch(step.step_id, expected=True)
        for assertion in said:
            touch(assertion.subject_id, is_said=True)
        for assertion in seen:
            touch(assertion.subject_id, is_seen=True)
        return cls(refs=refs)

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.refs))

    def said_ids(self) -> tuple[str, ...]:
        return tuple(sorted(k for k, v in self.refs.items() if v.said))

    def seen_ids(self) -> tuple[str, ...]:
        return tuple(sorted(k for k, v in self.refs.items() if v.seen))

    def expected_ids(self) -> tuple[str, ...]:
        return tuple(sorted(k for k, v in self.refs.items() if v.expected))

    def has(self, subject_id: str) -> bool:
        return subject_id in self.refs

    @property
    def seen_not_said(self) -> tuple[str, ...]:
        """Candidates for omission findings. Only interesting when enabled."""
        return tuple(sorted(k for k, v in self.refs.items() if v.seen and not v.said))

    @property
    def said_not_seen(self) -> tuple[str, ...]:
        """Claimed but never observed. Usually insufficient evidence, not a lie."""
        return tuple(sorted(k for k, v in self.refs.items() if v.said and not v.seen))

    @property
    def expected_not_done(self) -> tuple[str, ...]:
        """Checklist steps with no trace on either side. Empty in open-ended mode."""
        return tuple(
            sorted(k for k, v in self.refs.items() if v.expected and not v.said and not v.seen)
        )
