"""Subject names: one spelling per object, decided by code rather than by a model.

Open-ended discovery means subject names arrive as free text ("the coffee cup",
"my mug", "Cup"). Two claims only join if they normalise to the same canonical id.
This module is the whole of that contract, and it fails loudly when a mapping is
ambiguous instead of silently picking one.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

UNSPECIFIED_TARGET = "unspecified_target"

_PRONOUNS = {
    # demonstratives
    "this",
    "that",
    "these",
    "those",
    # object / thing
    "it",
    "its",
    "itself",
    "one",
    "ones",
    # masculine
    "he",
    "him",
    "his",
    "himself",
    # feminine
    "she",
    "her",
    "hers",
    "herself",
    # plural / neutral
    "they",
    "them",
    "theirs",
    "themselves",
}
_DETERMINERS = {
    # articles
    "the",
    "a",
    "an",
    # possessives
    "my",
    "your",
    "our",
    "their",
    "his",
    "her",
    "its",
    # demonstratives: "this mug" is a mug, not a subject named "this_mug"
    "this",
    "that",
    "these",
    "those",
    UNSPECIFIED_TARGET,
}


class AliasError(ValueError):
    """Raised when an alias table is ambiguous or a name cannot be normalised."""


def normalize_subject(raw: str) -> str:
    """Return the canonical spelling for a spoken subject name.

    ``"The Coffee Cup"`` -> ``"coffee_cup"``. A bare pronoun becomes
    ``"unspecified_target"``; resolution of that happens later, and only in code.
    """
    text = unicodedata.normalize("NFKC", raw).strip().casefold()
    text = re.sub(r"'s\b", "", text)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise AliasError(f"cannot normalise empty subject: {raw!r}")
    if text in _PRONOUNS:
        return UNSPECIFIED_TARGET

    words = text.split(" ")
    while words and words[0] in _DETERMINERS:
        words.pop(0)
    if not words:
        return UNSPECIFIED_TARGET
    return "_".join(words)


@dataclass(frozen=True, slots=True)
class AliasTable:
    """Immutable alias -> canonical-id mapping."""

    lookup: Mapping[str, str]

    @classmethod
    def empty(cls) -> AliasTable:
        return cls(MappingProxyType({}))

    @classmethod
    def from_groups(
        cls,
        groups: Mapping[str, Sequence[str]],
        *,
        include_canonical: bool = True,
    ) -> AliasTable:
        """Build from ``{canonical: [alias, ...]}``.

        Raises if one spelling would map to two different objects, or if an alias
        is a bare pronoun. Both are unrecoverable later: a silent choice here
        becomes a wrong finding downstream.
        """
        lookup: dict[str, str] = {}
        for canonical, aliases in groups.items():
            canon = normalize_subject(canonical)
            if canon == UNSPECIFIED_TARGET:
                raise AliasError(f"canonical name is a pronoun: {canonical!r}")
            names = [canonical, *aliases] if include_canonical else list(aliases)
            for name in names:
                key = normalize_subject(name)
                if key == UNSPECIFIED_TARGET:
                    raise AliasError(f"alias {name!r} for {canonical!r} is a pronoun")
                existing = lookup.get(key)
                if existing is not None and existing != canon:
                    raise AliasError(f"alias {name!r} maps to both {existing!r} and {canon!r}")
                lookup[key] = canon
        return cls(MappingProxyType(lookup))

    def resolve(self, raw: str) -> str:
        """Map a spoken name to its canonical id.

        Unknown names are returned normalised rather than dropped: open-ended mode
        has to be able to talk about things nobody pre-registered.
        """
        key = normalize_subject(raw)
        if key == UNSPECIFIED_TARGET:
            return UNSPECIFIED_TARGET
        return self.lookup.get(key, key)

    def canonical_ids(self) -> frozenset[str]:
        return frozenset(self.lookup.values())
