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
from ..voice import BUILTIN_VOICE_NAME, get_builtin_voice_id

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


def _dialogue_info(job_payload: dict | None) -> tuple[int, list[dict]]:
    """Return (speaker_count, dialogue_segments) from a job payload dict."""
    if not job_payload:
        return 1, []
    segs = job_payload.get("dialogue_segments")
    if segs:
        speakers = set(seg.get("speaker", "") for seg in segs)
        return max(1, len(speakers)), list(segs)
    return 1, []


def _chunks_on_disk(narration_id: str, count: int) -> int:
    if count <= 0:
        return 0
    base = storage.narration_chunk_dir(narration_id)
    done = 0
    for i in range(count):
        if (base / f"chunk_{i:03d}.wav").is_file():
            done += 1
    return done


def _serialize(narration: Narration, job_payload: dict | None = None) -> dict:
    chunks = json.loads(narration.chunks_json or "[]")
    done = _chunks_on_disk(narration.id, len(chunks))
    speaker_count, dialogue_segs = _dialogue_info(job_payload)
    return {
        "id": narration.id,
        "voice_id": narration.voice_id,
        "title": narration.title,
        "script": narration.script,
        "delivery_direction": narration.delivery_direction,
        "language": narration.language,
        "status": narration.status,
        "dialogue_speaker_count": speaker_count,
        "dialogue_segments": dialogue_segs,
        "chunk_count": len(chunks),
        "chunks_done": done,
        "duration_sec": narration.duration_sec,
        "sample_rate": narration.sample_rate,
        "error": narration.error,
        "created_at": narration.created_at,
    }


@router.get("", response_model=list[NarrationListResponse])
def list_narrations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    builtin_id = get_builtin_voice_id()

    rows = db.execute(
        select(Narration, Voice.name)
        .join(Voice, Narration.voice_id == Voice.id)
        .where(
            (Narration.owner_id == user.id)
            & ((Voice.owner_id == user.id) | (Voice.id == builtin_id))
        )
        .order_by(Narration.created_at.desc())
    ).all()

    if not rows:
        return []

    narration_ids = [n.id for n, _ in rows]

    latest_jobs = db.execute(
        select(Job.narration_id, Job.payload_json)
        .where(Job.narration_id.in_(narration_ids))
        .where(Job.owner_id == user.id)
        .where(Job.narration_id.isnot(None))
    ).all()

    payload_by_narration = {
        narration_id: payload_json
        for narration_id, payload_json in latest_jobs
    }

    latest_payload_by_narration: dict[str, dict | None] = {}
    for narration_id in narration_ids:
        payloads_for_narration = [
            json.loads(payload) if payload else None
            for (nid, payload) in latest_jobs
            if nid == narration_id
        ]
        latest_payload_by_narration[narration_id] = payloads_for_narration[-1] if payloads_for_narration else None

    results: list[NarrationListResponse] = []
    for n, voice_name in rows:
        job_payload = latest_payload_by_narration.get(n.id)
        speaker_count, _ = _dialogue_info(job_payload)
        results.append(
            NarrationListResponse(
                id=n.id,
                title=n.title,
                voice_id=n.voice_id if n.voice_id != builtin_id else None,
                voice_name=None if n.voice_id == builtin_id else voice_name,
                voice_source="custom_voice" if n.voice_id == builtin_id else None,
                dialogue_speaker_count=speaker_count,
                status=n.status,
                duration_sec=n.duration_sec,
                created_at=n.created_at,
            )
        )
    return results


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
    # A voice may narrate through its derived clone prompt (the usual path) OR
    # through zero-shot cloning straight from its reference audio: as long as
    # one artifact exists the worker can synthesize. This lets a freshly
    # uploaded cloned voice (which registers approved with reference audio
    # before its clone_prompt job lands) generate immediately, while an
    # approved voice that is temporarily `designing` during a redesign keeps
    # narrating because its saved prompt remains intact.
    has_prompt = bool(voice.prompt_pt_path) and storage.safe_resolve(voice.prompt_pt_path) is not None
    has_reference = bool(voice.reference_audio_path) and storage.safe_resolve(voice.reference_audio_path) is not None
    if not has_prompt and not has_reference:
        raise HTTPException(
            status_code=409,
            detail="Voice must have an approved clone prompt or reference audio before narration.",
        )

    script = body.script.strip()
    if not script:
        raise HTTPException(status_code=422, detail="Script cannot be empty.")
    try:
        chunks, sequence = chunking.chunk_script_with_pauses(
            script, settings.max_chunk_words
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

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

    payload = job_service.narration_payload(narration, chunks, sequence)
    job = job_service.enqueue(
        db,
        owner_id=user.id,
        type_="narration",
        payload=payload,
        voice_id=voice.id,
        narration_id=narration.id,
    )
    db.commit()
    db.refresh(narration)
    job_payload = json.loads(job.payload_json) if job.payload_json else None
    return _serialize(narration, job_payload)


@router.get("/{narration_id}", response_model=NarrationResponse)
def get_narration(
    narration_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    narration = _get_owned_narration(db, narration_id, user)
    latest_job = db.execute(
        select(Job)
        .where(Job.narration_id == narration_id, Job.owner_id == user.id)
        .order_by(Job.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    job_payload = json.loads(latest_job.payload_json) if latest_job and latest_job.payload_json else None
    return _serialize(narration, job_payload)


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
