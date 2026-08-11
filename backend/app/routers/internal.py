"""Internal API consumed by the GPU worker (and the mock worker).

Authenticated with the worker bearer token. The worker never sees database,
storage, or OAuth credentials; it receives job payloads and returns artifacts
through these endpoints (see docs/MVP_ARCHITECTURE.md section 3.6).
"""
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.orm import Session

from .. import audio, jobs as job_service
from ..config import get_settings
from ..db import get_db
from ..deps import require_worker
from ..models import Job
from ..schemas import ArtifactUploadResponse, CompleteRequest, FailRequest, JobClaim

router = APIRouter(prefix="/internal", tags=["internal"])
settings = get_settings()


def _get_job(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.post("/jobs/poll", response_model=JobClaim | None)
def poll_job(
    _: None = Depends(require_worker),
    db: Session = Depends(get_db),
):
    job = job_service.claim_next(db)
    if job is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    payload = json.loads(job.payload_json)
    db.commit()
    return JobClaim(job_id=job.id, type=job.type, payload=payload)


@router.post("/jobs/{job_id}/artifact", response_model=ArtifactUploadResponse)
async def upload_artifact(
    job_id: str,
    field: str = Form(...),
    file: UploadFile = File(...),
    _: None = Depends(require_worker),
    db: Session = Depends(get_db),
):
    job = _get_job(db, job_id)
    if job.status != "running":
        raise HTTPException(status_code=409, detail="Job is not running.")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds size limit.")

    try:
        if field in ("reference_audio",) or field.startswith("chunk_"):
            audio.validate_wav_bytes(data, settings.max_upload_bytes)
        job_service.store_artifact(db, job, field, data)
    except (audio.AudioError, ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    db.commit()
    return ArtifactUploadResponse(field=field, stored=True)


@router.post("/jobs/{job_id}/complete")
def complete_job(
    job_id: str,
    body: CompleteRequest,
    _: None = Depends(require_worker),
    db: Session = Depends(get_db),
):
    job = _get_job(db, job_id)
    if job.status != "running":
        raise HTTPException(status_code=409, detail="Job is not running.")
    try:
        job_service.complete_job(db, job, body.sample_rate, body.durations)
    except (audio.AudioError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/fail")
def fail_job(
    job_id: str,
    body: FailRequest,
    _: None = Depends(require_worker),
    db: Session = Depends(get_db),
):
    job = _get_job(db, job_id)
    if job.status != "running":
        raise HTTPException(status_code=409, detail="Job is not running.")
    job_service.fail_job(db, job, body.error)
    db.commit()
    return {"ok": True}
