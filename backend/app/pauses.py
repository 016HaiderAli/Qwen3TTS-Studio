"""Pause-tag parsing for narration scripts (Phase 5C).

Recognizes inline pause tags of the form::

    [Pause: 1.5s]   [Pause: 500ms]   [pause: 2S]

The pattern is case-insensitive and tolerates flexible whitespace between the
bracket, value, and unit. Durations are normalized to float seconds, and pause
tags act as hard split points: text between tags becomes separate spoken
pieces, so the completion stage can stitch zero-filled PCM16 silence buffers
at exactly the position the user placed each tag.
"""
import re
from dataclasses import dataclass

PAUSE_TAG_PATTERN = re.compile(r"\[Pause:\s*(\d+(?:\.\d+)?)\s*(s|ms)\s*\]", re.IGNORECASE)

# Safety clamp: a pause is an intentional dramatic beat, not a file-size
# weapon. 60 seconds comfortably covers any real dramatic pause while keeping
# the generated silence buffer (48 KB per second at 24 kHz PCM16) bounded.
MAX_PAUSE_SECONDS = 60.0


@dataclass(frozen=True)
class PauseItem:
    """One element of a pause-split script sequence.

    ``kind`` is ``"speech"`` (text to synthesize) or ``"pause"`` (a silence
    buffer of ``duration_sec`` seconds). Speech items carry the stripped text;
    pause items carry only the duration.
    """

    kind: str
    text: str = ""
    duration_sec: float = 0.0


def parse_pause_seconds(value: str, unit: str) -> float:
    """Convert a pause tag's numeric value and unit into float seconds.

    ``s`` maps to seconds as-is; ``ms`` divides by 1000 (so ``[Pause: 500ms]``
    becomes 0.5 seconds). Values above ``MAX_PAUSE_SECONDS`` are clamped.
    """
    amount = float(value)
    if unit.lower() == "ms":
        amount = amount / 1000.0
    return min(amount, MAX_PAUSE_SECONDS)


def extract_pause_seconds(tag_text: str) -> float | None:
    """Return the pause duration in seconds for a single tag string.

    Returns ``None`` when ``tag_text`` is not exactly one pause tag.
    """
    match = PAUSE_TAG_PATTERN.fullmatch(tag_text.strip())
    if match is None:
        return None
    return parse_pause_seconds(match.group(1), match.group(2))


def strip_pause_tags(text: str) -> str:
    """Remove every pause tag and collapse the leftover whitespace."""
    return re.sub(r"\s+", " ", PAUSE_TAG_PATTERN.sub(" ", text)).strip()


def has_pause_tags(text: str) -> bool:
    """Whether the text contains at least one pause tag."""
    return PAUSE_TAG_PATTERN.search(text) is not None


def split_on_pauses(text: str) -> list[PauseItem]:
    """Split a script into an ordered sequence of speech pieces and pauses.

    Pause tags are hard split points. Empty speech pieces are dropped, so
    leading, trailing, or consecutive tags never produce empty chunks. The
    returned list preserves exact script order. A script without pause tags
    yields a single speech item with the original (stripped) text untouched.
    """
    if not PAUSE_TAG_PATTERN.search(text):
        stripped = text.strip()
        return [PauseItem(kind="speech", text=stripped)] if stripped else []

    items: list[PauseItem] = []
    cursor = 0
    for match in PAUSE_TAG_PATTERN.finditer(text):
        piece = text[cursor : match.start()].strip()
        if piece:
            items.append(PauseItem(kind="speech", text=piece))
        items.append(
            PauseItem(
                kind="pause",
                duration_sec=parse_pause_seconds(match.group(1), match.group(2)),
            )
        )
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        items.append(PauseItem(kind="speech", text=tail))
    return items
