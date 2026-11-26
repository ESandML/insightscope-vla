"""The closed vocabulary of things an audit can assert.

Subjects (which object) are open-ended: they come from the transcript, because a user
can talk about anything on their desk. Attributes (what we assert about that object)
are fixed, because deterministic rules need a finite set of comparisons to make.

Keeping this list short is a feature. Every attribute added here needs coercion rules
and at least one reconciliation rule, so growth should be deliberate.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

AttributeValue = bool | int | str


class OntologyError(ValueError):
    """Raised when a model-supplied value cannot be read as the declared attribute."""


class Attribute(StrEnum):
    """What can be said about a subject."""

    PRESENCE = "presence"
    OPEN_CLOSED = "open_closed_state"
    LOCATION = "location"
    COUNT = "count"
    ACTION_COMPLETED = "action_completed"
    STEP_COMPLETED = "step_completed"

    @property
    def subject_kind(self) -> Literal["object", "step"]:
        """Steps are events, not objects; rules must never join across the two.

        ``action_completed`` is an action *on an object* ("stir the coffee"), so it
        stays on the object side. Only checklist steps are their own kind.
        """
        if self is Attribute.STEP_COMPLETED:
            return "step"
        return "object"


_TRUTHY = {
    "true",
    "yes",
    "present",
    "visible",
    "there",
    "done",
    "completed",
    "on",
    "1",
}
_FALSY = {
    "false",
    "no",
    "absent",
    "missing",
    "not_present",
    "not_visible",
    "gone",
    "off",
    "undone",
    "incomplete",
    "0",
    "none",
}
_OPEN_CLOSED = {
    "open": "open",
    "opened": "open",
    "closed": "closed",
    "close": "closed",
    "shut": "closed",
    "ajar": "ajar",
    "cracked": "ajar",
    "half_open": "ajar",
}

_MAX_COUNT = 1000


def normalize_token(value: str) -> str:
    """Fold a short free-text value into a stable token: ``Left of Laptop`` -> ``left_of_laptop``."""
    token = value.strip().casefold().replace("'", "")
    token = re.sub(r"[^\w]+", "_", token)
    return token.strip("_")


def normalize_action(value: str) -> str:
    """Canonicalise a spoken action: ``Wipe the Counter`` -> ``wipe_the_counter``.

    The action is part of the assertion identity, so this must be deterministic and
    strict: an empty action is an error, not a wildcard.
    """
    token = normalize_token(value)
    if not token:
        raise OntologyError(f"empty action: {value!r}")
    return token


def coerce_value(attribute: Attribute, value: Any) -> AttributeValue:
    """Return the canonical value for ``attribute``, or raise.

    Models are allowed to be sloppy ("shut", "3", "yes") but not vague. An
    unreadable value is an error we can see and test, not something to guess at.
    """
    if attribute in (
        Attribute.PRESENCE,
        Attribute.ACTION_COMPLETED,
        Attribute.STEP_COMPLETED,
    ):
        return _coerce_bool(attribute, value)
    if attribute is Attribute.OPEN_CLOSED:
        return _coerce_open_closed(attribute, value)
    if attribute is Attribute.COUNT:
        return _coerce_count(attribute, value)
    if attribute is Attribute.LOCATION:
        return _coerce_location(attribute, value)
    raise OntologyError(f"unknown attribute: {attribute!r}")


def _coerce_bool(attribute: Attribute, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        token = normalize_token(value)
        if token in _TRUTHY:
            return True
        if token in _FALSY:
            return False
    raise OntologyError(f"{attribute}: cannot read {value!r} as true/false")


def _coerce_open_closed(attribute: Attribute, value: Any) -> str:
    if isinstance(value, str):
        canonical = _OPEN_CLOSED.get(normalize_token(value))
        if canonical is not None:
            return canonical
    raise OntologyError(f"{attribute}: expected open/closed/ajar, got {value!r}")


def _coerce_count(attribute: Attribute, value: Any) -> int:
    number: int | None = None
    if isinstance(value, bool):
        number = None
    elif isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            number = int(text)
    if number is None:
        raise OntologyError(f"{attribute}: expected a whole number, got {value!r}")
    if not 0 <= number <= _MAX_COUNT:
        raise OntologyError(f"{attribute}: count {number} outside 0..{_MAX_COUNT}")
    return number


def _coerce_location(attribute: Attribute, value: Any) -> str:
    if not isinstance(value, str):
        raise OntologyError(f"{attribute}: expected a place name, got {value!r}")
    token = normalize_token(value)
    if not token:
        raise OntologyError(f"{attribute}: empty location")
    return token
