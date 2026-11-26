"""Build the client triple from a user-facing choice.

The CLI and the UI both call this, so "fake / ollama / cassette" means the same thing
in both places. Import of ``openai``/``instructor`` stays lazy: the core install never
needs them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from insightscope.clients.cassettes import Cassette, CassettePlayer, CassetteRecorder
from insightscope.clients.fake import FakeTextClient, FakeVisionClient
from insightscope.config import Settings


@dataclass(frozen=True, slots=True)
class ClientTriple:
    text: Any
    vision: Any
    generator: Any
    cassette: Cassette | None = None


def build_clients(
    *,
    kind: str = "fake",
    text_model: str | None = None,
    vision_model: str | None = None,
    base_url: str | None = None,
    record: Path | None = None,
    replay: Path | None = None,
) -> ClientTriple:
    """``kind`` is one of ``fake``, ``ollama``, ``cassette``."""
    if kind == "cassette":
        if replay is None:
            raise ValueError("cassette replay needs a cassette file")
        player = CassettePlayer(Cassette.load(replay))
        return ClientTriple(text=player, vision=player, generator=player)

    if kind == "fake":
        fake = FakeTextClient()
        triple = ClientTriple(
            text=fake,
            vision=FakeVisionClient(),
            generator=fake,
        )
    elif kind == "ollama":
        triple = _ollama_triple(
            text_model=text_model,
            vision_model=vision_model,
            base_url=base_url,
        )
    else:
        raise ValueError(f"unknown client kind: {kind!r}")

    if record is None:
        return triple

    cassette = Cassette(Path(record))
    return ClientTriple(
        text=CassetteRecorder(triple.text, cassette),
        vision=CassetteRecorder(triple.vision, cassette),
        generator=CassetteRecorder(triple.generator, cassette),
        cassette=cassette,
    )


def _ollama_triple(
    *,
    text_model: str | None,
    vision_model: str | None,
    base_url: str | None,
) -> ClientTriple:
    from insightscope.clients.openai_compat import OllamaClients

    settings = Settings()
    overrides: dict[str, Any] = {}
    if text_model:
        overrides["text_model"] = text_model
    if vision_model:
        overrides["vision_model"] = vision_model
    if base_url:
        overrides["llm_base_url"] = base_url
    if overrides:
        settings = settings.model_copy(update=overrides)

    ollama = OllamaClients(settings=settings)
    return ClientTriple(text=ollama, vision=ollama, generator=ollama)
