"""Job status endpoints (user-facing)."""
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..db import get_db
from ..deps import get_current_user
from ..models import Job, Narration, User
from ..schemas import JobResponse, JobStatusResponse

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _get_owned_job(db: Session, job_id: str, user: User) -> Job:
    row = db.execute(
        select(Job).where(Job.id == job_id, Job.owner_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return row


@router.get("", response_model=list[JobResponse])
def list_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(Job)
        .where(Job.owner_id == user.id)
        .order_by(Job.created_at.desc())
        .limit(50)
    ).scalars().all()
    return rows


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_job(db, job_id, user)
    narration = None
    chunk_total = 0
    chunk_done = 0
    if job.narration_id:
        narration = db.get(Narration, job.narration_id)
        if narration is not None:
            chunks = json.loads(narration.chunks_json or "[]")
            chunk_total = len(chunks)
            base = storage.narration_chunk_dir(narration.id)
            chunk_done = sum(
                1 for i in range(chunk_total) if (base / f"chunk_{i:03d}.wav").is_file()
            )
    return JobStatusResponse(
        job=JobResponse.model_validate(job),
        narration=(
            {
                "id": narration.id,
                "voice_id": narration.voice_id,
                "title": narration.title,
                "script": narration.script,
                "delivery_direction": narration.delivery_direction,
                "language": narration.language,
                "status": narration.status,
                "chunk_count": chunk_total,
                "chunks_done": chunk_done,
                "duration_sec": narration.duration_sec,
                "sample_rate": narration.sample_rate,
                "error": narration.error,
                "created_at": narration.created_at,
            }
            if narration is not None
            else None
        ),
        chunk_total=chunk_total,
        chunk_done=chunk_done,
    )
