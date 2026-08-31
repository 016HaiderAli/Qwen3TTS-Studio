"""Built-in Qwen CustomVoice speakers: catalog listing and generation trigger."""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import jobs as job_service
from .. import pauses
from ..custom_voices import get_speaker, is_known_speaker, list_speakers
from ..db import get_db
from ..deps import get_current_user
from ..dialogue import DialogueSegment, parse_dialogue_script
from ..models import Narration, User
from ..schemas import (
    BuiltinVoiceGenerateRequest,
    BuiltinVoiceInfo,
    NarrationResponse,
)
from ..voice import get_builtin_voice_id

router = APIRouter(prefix="/api/builtin-voices", tags=["builtin-voices"])

# Historical inter-turn silence (see complete_job custom_voice concat).
TURN_GAP_SECONDS = 0.3


@router.get("", response_model=list[BuiltinVoiceInfo])
def list_builtin_voices():
    """Return all 9 Qwen3-TTS CustomVoice speakers."""
    return [BuiltinVoiceInfo(id=s.id, description=s.description, native_language=s.native_language) for s in list_speakers()]


def _validate_dialogue_segments(
    segments: list[DialogueSegmentPayload],
) -> list[DialogueSegment]:
    """Validate and normalise dialogue segments from an API payload."""
    result: list[DialogueSegment] = []
    for seg in segments:
        speaker = seg.speaker.strip()
        if not speaker:
            raise HTTPException(status_code=400, detail="Each dialogue segment must have a non-empty speaker name.")
        if not is_known_speaker(speaker):
            raise HTTPException(status_code=400, detail=f"Unknown speaker in dialogue: {speaker!r}")
        text = seg.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="Each dialogue segment must have non-empty text.")
        result.append(
            DialogueSegment(
                speaker=speaker,
                text=text,
                segment_instruct=seg.instruct.strip(),
            )
        )
    return result


def _apply_pause_splits(
    segments: list[DialogueSegment],
    default_instruct: str = "",
) -> tuple[list[dict], list[dict] | None]:
    """Split segment texts on ``[Pause: ...]`` tags (Phase 5C).

    Pause tags are hard split points: each speech piece becomes its own
    dialogue segment (same speaker and instruct), so the worker generates one
    WAV per piece and the completion stage can stitch zero-filled silence at
    exactly the tagged positions. The returned sequence records the exact
    speech/pause order, with ``gap`` entries (0.3 s) between consecutive input
    segments to preserve the historical inter-turn silence.

    Returns ``(dialogue_segments, sequence)``. When no input text contains a
    pause tag, the segments pass through unchanged and the sequence is None,
    leaving existing behavior untouched. ``default_instruct`` fills the piece
    instruct for segments that carry none (used when a single-speaker script
    would otherwise have been generated as one chunk with the global
    instruct).

    Raises:
        HTTPException: 422 when no speech pieces remain (pause-only script).
    """
    has_pause = any(pauses.has_pause_tags(s.text) for s in segments)
    if not has_pause:
        return (
            [
                {"speaker": s.speaker, "text": s.text, "instruct": s.segment_instruct}
                for s in segments
            ],
            None,
        )

    speech: list[dict] = []
    sequence: list[dict] = []
    for pos, seg in enumerate(segments):
        if pos > 0:
            sequence.append({"type": "gap", "duration_sec": TURN_GAP_SECONDS})
        for item in pauses.split_on_pauses(seg.text):
            if item.kind == "pause":
                sequence.append(
                    {"type": "pause", "duration_sec": item.duration_sec}
                )
                continue
            sequence.append({"type": "speech", "chunk_index": len(speech)})
            speech.append(
                {
                    "speaker": seg.speaker,
                    "text": item.text,
                    "instruct": seg.segment_instruct or default_instruct,
                }
            )

    if not speech:
        raise HTTPException(
            status_code=422, detail="Script contains no speakable text."
        )
    return speech, sequence


@router.post("/generate", response_model=NarrationResponse, status_code=status.HTTP_201_CREATED)
def generate_builtin_voice(
    body: BuiltinVoiceGenerateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not is_known_speaker(body.speaker):
        raise HTTPException(status_code=400, detail=f"Unknown speaker: {body.speaker!r}")

    speaker_info = get_speaker(body.speaker)
    instruct = body.instruct.strip()
    dialogue_segments: list[dict] | None = None
    sequence: list[dict] | None = None

    if body.dialogue_segments is not None:
        validated = _validate_dialogue_segments(body.dialogue_segments)
        if any(pauses.has_pause_tags(s.text) for s in validated):
            dialogue_segments, sequence = _apply_pause_splits(validated)
            script = " | ".join(
                f"[{seg['speaker']}] {seg['text']}" for seg in dialogue_segments
            )
        else:
            script = " | ".join(f"[{s.speaker}] {s.text}" for s in validated)
            dialogue_segments = [
                {"speaker": s.speaker, "text": s.text, "instruct": s.segment_instruct}
                for s in validated
            ]
    else:
        script = body.script.strip()
        if not script:
            raise HTTPException(status_code=422, detail="Script cannot be empty.")
        parsed = parse_dialogue_script(script, body.speaker)
        validated_segments = [s for s in parsed if is_known_speaker(s.speaker)]
        merged: list[DialogueSegment] = []
        for s in validated_segments:
            if (
                merged
                and merged[-1].speaker == s.speaker
                and not merged[-1].segment_instruct
                and not s.segment_instruct
            ):
                merged[-1] = DialogueSegment(
                    speaker=s.speaker,
                    text=f"{merged[-1].text} {s.text}",
                    segment_instruct="",
                )
            else:
                merged.append(s)
        if any(pauses.has_pause_tags(s.text) for s in parsed):
            # Pause-aware path: each pause tag becomes its own silence entry,
            # so pieces must map 1:1 to worker-generated segment WAVs. The
            # single-segment case inherits the global instruct (it would
            # otherwise have been generated as one chunk with it).
            pieces = merged if merged else parsed
            default_instruct = instruct if len(pieces) == 1 else ""
            dialogue_segments, sequence = _apply_pause_splits(
                pieces, default_instruct
            )
            script = " | ".join(
                f"[{seg['speaker']}] {seg['text']}" for seg in dialogue_segments
            )
        elif len(merged) > 1:
            script = " | ".join(f"[{s.speaker}] {s.text}" for s in merged)
            dialogue_segments = [
                {"speaker": s.speaker, "text": s.text, "instruct": s.segment_instruct}
                for s in merged
            ]

    narration = Narration(
        owner_id=user.id,
        voice_id=get_builtin_voice_id(),
        title=body.title.strip() or f"Built-in: {speaker_info.id}",
        script=script,
        delivery_direction=instruct,
        language=body.language,
        status="queued",
        chunks_json=json.dumps([s["text"] for s in dialogue_segments]) if dialogue_segments else json.dumps([script]),
        chunk_durations_json="[]",
    )
    db.add(narration)
    db.flush()

    payload = job_service.builtin_voice_payload(
        narration,
        speaker=body.speaker,
        instruct=instruct,
        dialogue_segments=dialogue_segments,
        sequence=sequence,
    )
    job_service.enqueue(
        db,
        owner_id=user.id,
        type_="custom_voice",
        payload=payload,
        narration_id=narration.id,
    )
    db.commit()
    db.refresh(narration)
    seg_count = max(1, len(set(s["speaker"] for s in dialogue_segments))) if dialogue_segments else 1
    return NarrationResponse(
        id=narration.id,
        voice_id=None,
        title=narration.title,
        script=narration.script,
        delivery_direction=narration.delivery_direction,
        language=narration.language,
        status=narration.status,
        voice_source="custom_voice",
        dialogue_speaker_count=seg_count,
        dialogue_segments=dialogue_segments or [],
        chunk_count=len(dialogue_segments) if dialogue_segments else 1,
        chunks_done=0,
        duration_sec=None,
        sample_rate=None,
        error=None,
        created_at=narration.created_at,
    )
