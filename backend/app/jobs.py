"""Job lifecycle: enqueue, claim, artifact handling, completion, failure.

The backend process is a single claimer: the worker pulls jobs via the internal
API and the backend transitions the `jobs` table rows. No broker is used
(see docs/MVP_ARCHITECTURE.md section 1.5).
"""
import base64
import json
import logging
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audio, storage
from .config import get_settings
from .models import Job, Narration, Voice

logger = logging.getLogger(__name__)
settings = get_settings()


# ---------- payload builders ----------
def design_payload(voice: Voice, language: str, instruct: str, text: str) -> dict:
    return {
        "voice_id": voice.id,
        "language": language,
        "instruct": instruct,
        "text": text,
    }


def clone_prompt_payload(voice: Voice) -> dict:
    ref_audio = storage.read_bytes(voice.reference_audio_path)
    return {
        "voice_id": voice.id,
        "language": voice.language,
        "ref_audio_b64": base64.b64encode(ref_audio).decode("ascii"),
        "ref_text": voice.reference_text,
    }


def narration_payload(narration: Narration, chunks: list[str]) -> dict:
    voice = narration.voice
    prompt = storage.read_bytes(voice.prompt_pt_path)
    return {
        "voice_id": voice.id,
        "narration_id": narration.id,
        "language": narration.language,
        "instruct": narration.delivery_direction,
        "chunks": chunks,
        "prompt_pt_b64": base64.b64encode(prompt).decode("ascii"),
    }


# ---------- enqueue ----------
def enqueue(
    db: Session,
    owner_id: str,
    type_: str,
    payload: dict,
    voice_id: str | None = None,
    narration_id: str | None = None,
) -> Job:
    job = Job(
        owner_id=owner_id,
        type=type_,
        status="queued",
        voice_id=voice_id,
        narration_id=narration_id,
        payload_json=json.dumps(payload),
        result_json="{}",
    )
    db.add(job)
    db.flush()
    return job


# ---------- claim ----------
def claim_next(db: Session) -> Job | None:
    """Claim the oldest queued job. Safe for a single backend process."""
    job = db.execute(
        select(Job)
        .where(Job.status == "queued")
        .order_by(Job.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    db.flush()
    return job


# ---------- artifacts ----------
def store_artifact(db: Session, job: Job, field: str, data: bytes) -> None:
    """Persist an uploaded artifact from the worker and update progress."""
    if job.type == "design" and field == "reference_audio":
        storage.write_bytes(storage.voice_reference_rel(job.voice_id), data)
        job.progress = 50
    elif job.type == "clone_prompt" and field == "prompt_pt":
        storage.write_bytes(storage.voice_prompt_rel(job.voice_id), data)
        job.progress = 50
    elif job.type == "narration" and field.startswith("chunk_"):
        try:
            index = int(field.split("_", 1)[1])
        except (ValueError, IndexError) as exc:
            raise ValueError(f"invalid chunk field: {field}") from exc
        storage.write_bytes(storage.narration_chunk_rel(job.narration_id, index), data)
        total = _chunk_count(job)
        job.progress = min(99, int((index + 1) * 100 / max(total, 1)))
    else:
        raise ValueError(f"unexpected artifact field for job type {job.type}: {field}")
    db.flush()


# ---------- completion ----------
def complete_job(
    db: Session,
    job: Job,
    sample_rate: int | None,
    durations: list[float],
) -> None:
    job.status = "succeeded"
    job.progress = 100
    job.result_json = json.dumps({"sample_rate": sample_rate, "durations": durations})
    db.flush()

    if job.type == "design":
        voice = db.get(Voice, job.voice_id)
        if voice is not None and voice.status == "designing":
            voice.status = "preview_ready"
            voice.reference_audio_path = storage.voice_reference_rel(voice.id)
    elif job.type == "clone_prompt":
        voice = db.get(Voice, job.voice_id)
        if voice is not None and voice.status == "preview_ready":
            voice.status = "approved"
            voice.prompt_pt_path = storage.voice_prompt_rel(voice.id)
    elif job.type == "narration":
        narration = db.get(Narration, job.narration_id)
        if narration is None:
            raise RuntimeError("narration record missing")
        count = _chunk_count(job)
        paths = storage.narration_chunk_paths(narration.id, count)
        existing = [p for p in paths if p.is_file()]
        if len(existing) != count:
            raise RuntimeError(f"expected {count} chunk files, found {len(existing)}")
        sr, duration = audio.concat_wav_files(
            existing, storage.root() / storage.narration_final_rel(narration.id)
        )
        # The sample rate parsed from the actual WAV chunks is authoritative for
        # the final narration; the worker-reported value is recorded for
        # cross-checking but never trusted over the artifact metadata.
        if sample_rate is not None and int(sample_rate) != int(sr):
            logger.warning(
                "job %s: worker reported sample_rate=%s but the concatenated "
                "WAV is %d Hz; using the WAV metadata",
                job.id,
                sample_rate,
                sr,
            )
        narration.final_audio_path = storage.narration_final_rel(narration.id)
        narration.sample_rate = int(sr)
        narration.duration_sec = duration
        narration.status = "ready"
        narration.chunk_durations_json = json.dumps(durations)
    db.flush()


# ---------- failure ----------
def fail_job(db: Session, job: Job, error: str) -> None:
    job.error = error[:4000]
    if job.attempts < settings.max_job_attempts:
        job.status = "queued"
        if job.type == "narration":
            shutil.rmtree(storage.narration_chunk_dir(job.narration_id), ignore_errors=True)
    else:
        job.status = "failed"
        _mark_failed_owner_object(db, job, error)
    db.flush()


def _mark_failed_owner_object(db: Session, job: Job, error: str) -> None:
    if job.type == "narration" and job.narration_id:
        narration = db.get(Narration, job.narration_id)
        if narration is not None:
            narration.status = "failed"
            narration.error = error[:4000]
    elif job.type in ("design", "clone_prompt") and job.voice_id:
        voice = db.get(Voice, job.voice_id)
        if voice is not None and voice.status in ("designing", "preview_ready"):
            voice.status = "draft"


# ---------- helpers ----------
def _chunk_count(job: Job) -> int:
    payload = json.loads(job.payload_json)
    return len(payload.get("chunks", []))


def clear_partial_chunks(narration_id: str) -> None:
    shutil.rmtree(storage.narration_chunk_dir(narration_id), ignore_errors=True)
