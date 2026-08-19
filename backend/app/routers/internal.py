"""Internal API consumed by the GPU worker (and the mock worker).

Authenticated with the worker bearer token. The worker never sees database,
storage, or OAuth credentials; it receives job payloads and returns artifacts
through these endpoints (see docs/MVP_ARCHITECTURE.md section 3.6).

Job ownership: in addition to the bearer token and the backend capability gate,
every artifact/complete/fail call must present the claim token that was minted
for its current claim (``X-Job-Claim-Token``). A worker whose claim was
superseded by lease recovery therefore cannot complete/fail the job it no
longer owns.
"""
import json
import secrets

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from .. import audio, jobs as job_service
from ..config import get_settings
from ..db import get_db
from ..deps import require_worker_backend
from ..models import Job
from ..schemas import ArtifactUploadResponse, CompleteRequest, FailRequest, JobClaim

router = APIRouter(prefix="/internal", tags=["internal"])
settings = get_settings()


def _get_job(db: Session, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def _require_matching_backend(job: Job, backend: str) -> None:
    """Only the backend a job was tagged for may touch it after it is claimed."""
    if job.required_backend != backend:
        raise HTTPException(
            status_code=403,
            detail=f"Job requires the {job.required_backend} worker.",
        )


def _require_claim_token(job: Job, request: Request) -> None:
    """Reject a worker that does not own the job's current claim.

    Runs after the status check, so a job that is no longer `running` is
    rejected with 409 regardless of the token. A `running` job whose claim was
    recovered and re-minted has a different token, so the superseded worker is
    also rejected with 409 and cannot corrupt the new owner's work.
    """
    presented = request.headers.get("X-Job-Claim-Token", "")
    if not job.claim_token or not secrets.compare_digest(presented, job.claim_token):
        raise HTTPException(status_code=409, detail="Job claim token mismatch.")


@router.post("/jobs/poll", response_model=JobClaim | None)
def poll_job(
    backend: str = Depends(require_worker_backend),
    db: Session = Depends(get_db),
):
    # Recovery is poll-triggered: requeue/fail any lease-expired running jobs
    # before claiming, so a dead worker's jobs are made claimable again without
    # a permanent background scheduler.
    job_service.recover_stale_jobs(db)
    job = job_service.claim_next(db, worker_backend=backend)
    if job is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    payload = json.loads(job.payload_json)
    db.commit()
    return JobClaim(
        job_id=job.id,
        type=job.type,
        payload=payload,
        claim_token=job.claim_token,
    )


@router.post("/jobs/{job_id}/artifact", response_model=ArtifactUploadResponse)
async def upload_artifact(
    job_id: str,
    request: Request,
    field: str = Form(...),
    file: UploadFile = File(...),
    backend: str = Depends(require_worker_backend),
    db: Session = Depends(get_db),
):
    job = _get_job(db, job_id)
    _require_matching_backend(job, backend)
    if job.status != "running":
        raise HTTPException(status_code=409, detail="Job is not running.")
    _require_claim_token(job, request)
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
    request: Request,
    body: CompleteRequest,
    backend: str = Depends(require_worker_backend),
    db: Session = Depends(get_db),
):
    job = _get_job(db, job_id)
    _require_matching_backend(job, backend)
    if job.status != "running":
        raise HTTPException(status_code=409, detail="Job is not running.")
    _require_claim_token(job, request)
    try:
        job_service.complete_job(db, job, body.sample_rate, body.durations)
    except (audio.AudioError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/fail")
def fail_job(
    job_id: str,
    request: Request,
    body: FailRequest,
    backend: str = Depends(require_worker_backend),
    db: Session = Depends(get_db),
):
    job = _get_job(db, job_id)
    _require_matching_backend(job, backend)
    if job.status != "running":
        raise HTTPException(status_code=409, detail="Job is not running.")
    _require_claim_token(job, request)
    job_service.fail_job(db, job, body.error)
    db.commit()
    return {"ok": True}
