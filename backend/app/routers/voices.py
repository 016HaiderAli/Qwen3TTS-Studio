"""Voice management and the voice-design workflow."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import jobs as job_service
from .. import storage
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Voice
from ..schemas import (
    VoiceCreate,
    VoiceDesignRequest,
    VoiceResponse,
)

router = APIRouter(prefix="/api/voices", tags=["voices"])
settings = get_settings()


def _get_owned_voice(db: Session, voice_id: str, user: User) -> Voice:
    voice = db.execute(
        select(Voice).where(Voice.id == voice_id, Voice.owner_id == user.id)
    ).scalar_one_or_none()
    if voice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Voice not found.")
    return voice


@router.get("", response_model=list[VoiceResponse])
def list_voices(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(Voice)
        .where(Voice.owner_id == user.id)
        .order_by(Voice.created_at.desc())
    ).scalars().all()
    return rows


@router.post("", response_model=VoiceResponse, status_code=status.HTTP_201_CREATED)
def create_voice(
    body: VoiceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.language not in settings.supported_languages:
        raise HTTPException(status_code=422, detail="Unsupported language.")
    voice = Voice(
        owner_id=user.id,
        name=body.name.strip(),
        language=body.language,
        description=body.description.strip(),
        reference_text=body.reference_text.strip(),
        status="draft",
    )
    db.add(voice)
    db.commit()
    db.refresh(voice)
    return voice


@router.get("/{voice_id}", response_model=VoiceResponse)
def get_voice(
    voice_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_voice(db, voice_id, user)


@router.post("/{voice_id}/design", response_model=VoiceResponse)
def design_voice(
    voice_id: str,
    body: VoiceDesignRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    voice = _get_owned_voice(db, voice_id, user)
    if body.language not in settings.supported_languages:
        raise HTTPException(status_code=422, detail="Unsupported language.")
    voice.description = body.description.strip()
    voice.reference_text = body.reference_text.strip()
    voice.language = body.language
    voice.status = "designing"
    payload = job_service.design_payload(
        voice, body.language, body.description.strip(), body.reference_text.strip()
    )
    job_service.enqueue(
        db,
        owner_id=user.id,
        type_="design",
        payload=payload,
        voice_id=voice.id,
    )
    db.commit()
    db.refresh(voice)
    return voice


@router.post("/{voice_id}/approve", response_model=VoiceResponse)
def approve_voice(
    voice_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    voice = _get_owned_voice(db, voice_id, user)
    if voice.status == "approving":
        raise HTTPException(
            status_code=409,
            detail="Approval is already in progress.",
        )
    if voice.status != "preview_ready":
        raise HTTPException(
            status_code=409,
            detail="Voice must have a generated preview before approval.",
        )
    if not voice.reference_audio_path:
        raise HTTPException(status_code=409, detail="No preview audio available.")
    claimed = db.execute(
        update(Voice)
        .where(Voice.id == voice.id, Voice.status == "preview_ready")
        .values(status="approving")
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Approval is already in progress.",
        )
    payload = job_service.clone_prompt_payload(voice)
    job_service.enqueue(
        db,
        owner_id=user.id,
        type_="clone_prompt",
        payload=payload,
        voice_id=voice.id,
    )
    db.commit()
    db.refresh(voice)
    return voice


@router.delete("/{voice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voice(
    voice_id: str,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    voice = _get_owned_voice(db, voice_id, user)
    db.delete(voice)
    db.commit()
    storage.remove_voice_artifacts(voice_id)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
