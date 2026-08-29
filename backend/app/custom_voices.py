"""Built-in Qwen CustomVoice speaker catalog.

Single source of truth for the predefined speakers shipped with the Qwen3-TTS
CustomVoice model family. Sourced from the official Qwen3-TTS model card
(https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice) — speaker ids
and their documented voice descriptions and native languages are taken from
there and not invented. Each speaker can still speak any language the model
supports; the ``native_language`` field is a recommendation for best quality.

The 0.6B and 1.7B CustomVoice variants expose the same nine speaker ids, so
this list is valid for both models.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CustomVoice:
    """One predefined Qwen CustomVoice speaker."""

    id: str
    description: str
    native_language: str
    notes: str = ""


# Order is the order shown in the UI. Mirrors the official model card order.
BUILTIN_SPEAKERS: tuple[CustomVoice, ...] = (
    CustomVoice(
        id="Vivian",
        description="Bright, slightly edgy young female voice.",
        native_language="Chinese",
    ),
    CustomVoice(
        id="Serena",
        description="Warm, gentle young female voice.",
        native_language="Chinese",
    ),
    CustomVoice(
        id="Uncle_Fu",
        description="Seasoned male voice with a low, mellow timbre.",
        native_language="Chinese",
    ),
    CustomVoice(
        id="Dylan",
        description="Youthful Beijing male voice with a clear, natural timbre.",
        native_language="Chinese (Beijing Dialect)",
    ),
    CustomVoice(
        id="Eric",
        description="Lively Chengdu male voice with a slightly husky brightness.",
        native_language="Chinese (Sichuan Dialect)",
    ),
    CustomVoice(
        id="Ryan",
        description="Dynamic male voice with strong rhythmic drive.",
        native_language="English",
    ),
    CustomVoice(
        id="Aiden",
        description="Sunny American male voice with a clear midrange.",
        native_language="English",
    ),
    CustomVoice(
        id="Ono_Anna",
        description="Playful Japanese female voice with a light, nimble timbre.",
        native_language="Japanese",
    ),
    CustomVoice(
        id="Sohee",
        description="Warm Korean female voice with rich emotion.",
        native_language="Korean",
    ),
)


_BUILTIN_BY_ID: dict[str, CustomVoice] = {s.id: s for s in BUILTIN_SPEAKERS}


def list_speakers() -> list[CustomVoice]:
    """Return all predefined speakers in UI order."""
    return list(BUILTIN_SPEAKERS)


def get_speaker(speaker_id: str) -> CustomVoice | None:
    """Return the speaker with the given id, or None if not a known speaker."""
    return _BUILTIN_BY_ID.get(speaker_id)


def is_known_speaker(speaker_id: str) -> bool:
    return speaker_id in _BUILTIN_BY_ID
