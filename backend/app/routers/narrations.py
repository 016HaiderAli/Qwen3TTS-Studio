"""Narration management: script input, chunking, job enqueue, history."""
import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import chunking
from .. import jobs as job_service
from .. import storage
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Job, Narration, User, Voice
from ..schemas import NarrationCreate, NarrationListResponse, NarrationResponse

router = APIRouter(prefix="/api/narrations", tags=["narrations"])
settings = get_settings()


def _get_owned_narration(db: Session, narration_id: str, user: User) -> Narration:
    row = db.execute(
        select(Narration).where(
            Narration.id == narration_id, Narration.owner_id == user.id
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Narration not found.")
    return row


def _serialize(narration: Narration) -> dict:
    chunks = json.loads(narration.chunks_json or "[]")
    done = _chunks_on_disk(narration.id, len(chunks))
    return {
        "id": narration.id,
        "voice_id": narration.voice_id,
        "title": narration.title,
        "script": narration.script,
        "delivery_direction": narration.delivery_direction,
        "language": narration.language,
        "status": narration.status,
        "chunk_count": len(chunks),
        "chunks_done": done,
        "duration_sec": narration.duration_sec,
        "sample_rate": narration.sample_rate,
        "error": narration.error,
        "created_at": narration.created_at,
    }


def _chunks_on_disk(narration_id: str, count: int) -> int:
    if count <= 0:
        return 0
    base = storage.narration_chunk_dir(narration_id)
    done = 0
    for i in range(count):
        if (base / f"chunk_{i:03d}.wav").is_file():
            done += 1
    return done


@router.get("", response_model=list[NarrationListResponse])
def list_narrations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(Narration, Voice.name)
        .join(Voice, Narration.voice_id == Voice.id)
        .where(Narration.owner_id == user.id)
        .order_by(Narration.created_at.desc())
    ).all()
    return [
        NarrationListResponse(
            id=n.id,
            title=n.title,
            voice_id=n.voice_id,
            voice_name=voice_name,
            status=n.status,
            duration_sec=n.duration_sec,
            created_at=n.created_at,
        )
        for n, voice_name in rows
    ]


@router.post("", response_model=NarrationResponse, status_code=status.HTTP_201_CREATED)
def create_narration(
    body: NarrationCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if len(body.script) > settings.max_script_chars:
        raise HTTPException(
            status_code=422,
            detail=f"Script exceeds {settings.max_script_chars} characters.",
        )
    if body.language not in settings.supported_languages:
        raise HTTPException(status_code=422, detail="Unsupported language.")

    voice = db.execute(
        select(Voice).where(Voice.id == body.voice_id, Voice.owner_id == user.id)
    ).scalar_one_or_none()
    if voice is None:
        raise HTTPException(status_code=404, detail="Voice not found.")
    if not voice.prompt_pt_path:
        raise HTTPException(
            status_code=409,
            detail="Voice must have an approved clone prompt before narration.",
        )

    script = body.script.strip()
    if not script:
        raise HTTPException(status_code=422, detail="Script cannot be empty.")
    chunks = chunking.chunk_script(script, settings.max_chunk_words)

    narration = Narration(
        owner_id=user.id,
        voice_id=voice.id,
        title=body.title.strip() or "Untitled narration",
        script=script,
        delivery_direction=body.delivery_direction.strip(),
        language=body.language,
        status="queued",
        chunks_json=json.dumps(chunks),
        chunk_durations_json="[]",
    )
    db.add(narration)
    db.flush()

    payload = job_service.narration_payload(narration, chunks)
    job_service.enqueue(
        db,
        owner_id=user.id,
        type_="narration",
        payload=payload,
        voice_id=voice.id,
        narration_id=narration.id,
    )
    db.commit()
    db.refresh(narration)
    return _serialize(narration)


@router.get("/{narration_id}", response_model=NarrationResponse)
def get_narration(
    narration_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _serialize(_get_owned_narration(db, narration_id, user))


@router.delete("/{narration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_narration(
    narration_id: str,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    narration = _get_owned_narration(db, narration_id, user)
    active = db.execute(
        select(Job.id).where(
            Job.narration_id == narration.id,
            Job.owner_id == user.id,
            Job.status.in_(["queued", "running"]),
        )
    ).first()
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="This narration is still being generated. Wait for it to finish before deleting.",
        )
    db.delete(narration)
    db.commit()
    storage.remove_narration_artifacts(narration_id)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
