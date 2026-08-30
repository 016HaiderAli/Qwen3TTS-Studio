"""Dialogue script parsing for multi-speaker narration.

Supports inline speaker tags of the form::

    [Speaker: Ryan] Hello! [Speaker: Serena] Hi there!

Each tag switches the active speaker for all subsequent text until the next tag.
Text before the first tag is attributed to the default speaker (the single voice
selected for the job).  Optional per-segment instructions can follow the speaker
name::

    [Speaker: Ryan] [energetic] Let's go! [Speaker: Serena] [calm] Take it slow.

Tags are stripped from the text passed to the TTS model; they only serve as
routing metadata for the chunking and speaker-assignment pipeline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TAG_PATTERN = re.compile(
    r"\[Speaker:\s*(?P<speaker>[^\]]+)\]"
    r"(?:\s*\[(?P<segment_instruct>[^\]]+)\])?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DialogueSegment:
    speaker: str
    text: str
    segment_instruct: str = ""


def parse_dialogue_script(
    script: str,
    default_speaker: str,
) -> list[DialogueSegment]:
    """Parse a dialogue script into ordered segments.

    Args:
        script: Raw script that may contain ``[Speaker: Name]`` tags and
            optional per-segment instruction tags ``[instruct]``.
        default_speaker: Speaker assigned to text that appears before any
            ``[Speaker: ...]`` tag, or when a tag references an unknown speaker.

    Returns:
        A list of ``DialogueSegment`` objects in the order they appear in
        the script.  Empty text blocks are skipped.

    Example:
        >>> parse_dialogue_script(
        ...     "Hello! [Speaker: Ryan] Let's go! [Speaker: Serena] Take it slow.",
        ...     default_speaker="Vivian",
        ... )
        [
            DialogueSegment(speaker="Vivian", text="Hello!"),
            DialogueSegment(speaker="Ryan", text="Let's go!"),
            DialogueSegment(speaker="Serena", text="Take it slow."),
        ]
    """
    segments: list[DialogueSegment] = []
    current_speaker = default_speaker
    current_instruct = ""
    cursor = 0

    for match in _TAG_PATTERN.finditer(script):
        # Text between the end of the last match (or script start) and the
        # start of this tag belongs to the current speaker.
        gap = script[cursor : match.start()].strip()
        if gap:
            segments.append(
                DialogueSegment(
                    speaker=current_speaker,
                    text=gap,
                    segment_instruct=current_instruct,
                )
            )
            current_instruct = ""

        # Switch speaker and capture optional per-segment instruction.
        raw_speaker = match.group("speaker").strip()
        if raw_speaker:
            current_speaker = raw_speaker

        seg_instruct = (match.group("segment_instruct") or "").strip()
        if seg_instruct:
            current_instruct = seg_instruct

        cursor = match.end()

    # Remaining text after the last tag.
    remainder = script[cursor:].strip()
    if remainder:
        segments.append(
            DialogueSegment(
                speaker=current_speaker,
                text=remainder,
                segment_instruct=current_instruct,
            )
        )

    # Merge consecutive segments with the same speaker (no tag between them).
    return _merge_consecutive(segments)


def _merge_consecutive(segments: list[DialogueSegment]) -> list[DialogueSegment]:
    """Collapse adjacent segments that share the same speaker and instruct."""
    if not segments:
        return []
    merged = [segments[0]]
    for seg in segments[1:]:
        last = merged[-1]
        if seg.speaker == last.speaker and seg.segment_instruct == last.segment_instruct:
            merged[-1] = DialogueSegment(
                speaker=last.speaker,
                text=f"{last.text} {seg.text}",
                segment_instruct=last.segment_instruct,
            )
        else:
            merged.append(seg)
    return merged
