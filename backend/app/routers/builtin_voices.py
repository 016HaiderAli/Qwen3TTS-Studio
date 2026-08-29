"""Built-in Qwen CustomVoice speakers: catalog listing and generation trigger."""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import jobs as job_service
from ..custom_voices import get_speaker, is_known_speaker, list_speakers
from ..db import get_db
from ..deps import get_current_user
from ..models import Narration, User
from ..schemas import (
    BuiltinVoiceGenerateRequest,
    BuiltinVoiceInfo,
    NarrationResponse,
)

router = APIRouter(prefix="/api/builtin-voices", tags=["builtin-voices"])


@router.get("", response_model=list[BuiltinVoiceInfo])
def list_builtin_voices():
    """Return all 9 Qwen3-TTS CustomVoice speakers."""
    return [BuiltinVoiceInfo(id=s.id, description=s.description, native_language=s.native_language) for s in list_speakers()]


@router.post("/generate", response_model=NarrationResponse, status_code=status.HTTP_201_CREATED)
def generate_builtin_voice(
    body: BuiltinVoiceGenerateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not is_known_speaker(body.speaker):
        raise HTTPException(status_code=400, detail=f"Unknown speaker: {body.speaker!r}")

    speaker_info = get_speaker(body.speaker)

    script = body.script.strip()
    if not script:
        raise HTTPException(status_code=422, detail="Script cannot be empty.")

    narration = Narration(
        owner_id=user.id,
        voice_id=None,
        title=body.title.strip() or f"Built-in: {speaker_info.id}",
        script=script,
        delivery_direction=body.instruct.strip(),
        language=body.language,
        status="queued",
        chunks_json=json.dumps([script]),
        chunk_durations_json="[]",
    )
    db.add(narration)
    db.flush()

    payload = job_service.builtin_voice_payload(
        narration,
        speaker=body.speaker,
        instruct=body.instruct,
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
    return NarrationResponse(
        id=narration.id,
        voice_id=None,
        title=narration.title,
        script=narration.script,
        delivery_direction=narration.delivery_direction,
        language=narration.language,
        status=narration.status,
        voice_source="custom_voice",
        chunk_count=1,
        chunks_done=0,
        duration_sec=None,
        sample_rate=None,
        error=None,
        created_at=narration.created_at,
    )
