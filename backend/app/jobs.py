"""Job lifecycle: enqueue, claim, lease, artifact handling, completion, failure.

The backend process is a single claimer: the worker pulls jobs via the internal
API and the backend transitions the `jobs` table rows. No broker is used
(see docs/MVP_ARCHITECTURE.md section 1.5).

Lease/recovery: every claim stamps `claimed_at` and mints an opaque
`claim_token` returned to the worker. A `running` job whose lease has expired
is recovered on the next poll (requeued for another attempt, or failed
terminally once `max_job_attempts` is exhausted), so a worker crash can never
leave a job permanently `running`. The claim token must be presented back on
artifact upload/complete/fail, so a late request from a superseded worker is
rejected and cannot corrupt a re-claimed job.
"""
import base64
import json
import logging
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audio, storage
from .config import get_settings
from .models import Job, Narration, Voice

logger = logging.getLogger(__name__)
settings = get_settings()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- payload builders ----------
def design_payload(voice: Voice, language: str, instruct: str, text: str) -> dict:
    return {
        "voice_id": voice.id,
        "language": language,
        "instruct": instruct,
        "text": text,
    }


def clone_prompt_payload(voice: Voice) -> dict:
    # The clone is built from the voice's draft preview (the audio the user
    # just approved), not the live reference: the previously approved
    # reference.wav is left untouched until the clone succeeds, when it is
    # promoted in complete_job. clone_prompt jobs are only ever enqueued by
    # approve_voice, at which point the preview always exists.
    ref_audio = storage.read_bytes(storage.voice_preview_rel(voice.id))
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
    required_backend: str | None = None,
) -> Job:
    job = Job(
        owner_id=owner_id,
        type=type_,
        status="queued",
        voice_id=voice_id,
        narration_id=narration_id,
        required_backend=required_backend or settings.default_job_backend,
        payload_json=json.dumps(payload),
        result_json="{}",
    )
    db.add(job)
    db.flush()
    return job


# ---------- claim ----------
def claim_next(db: Session, worker_backend: str) -> Job | None:
    """Claim the oldest queued job the worker's backend capability can serve.

    Only jobs tagged with the same ``required_backend`` as the requesting worker
    are claimable, so a mock worker can never take a job that needs the real
    qwen worker (and vice versa). Safe for a single backend process.

    Claiming stamps the lease (`claimed_at`) and mints a fresh `claim_token`
    that the worker must present on every artifact/complete/fail call.
    """
    job = db.execute(
        select(Job)
        .where(Job.status == "queued", Job.required_backend == worker_backend)
        .order_by(Job.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.claimed_at = _utcnow()
    job.claim_token = secrets.token_urlsafe(32)
    db.flush()
    return job


# ---------- stale-job recovery ----------
def recover_stale_jobs(db: Session) -> int:
    """Requeue or terminally fail `running` jobs whose lease has expired.

    Runs opportunistically from the worker poll (no background scheduler): the
    worker is the only entity that can process a recovered job anyway. A job is
    stale when it is still `running` past ``job_lease_seconds`` since its last
    claim. NULL ``claimed_at`` (a pre-deployment row, or a row whose lease was
    never stamped) is treated as stale so it is still recovered rather than
    stuck forever. Returns the number of jobs recovered.

    Recovery respects the existing attempt semantics: stale jobs with attempts
    left are requeued (the next claim increments `attempts`), and stale jobs at
    `max_job_attempts` become `failed` with the owning voice/narration released
    from its in-progress state.
    """
    deadline = _utcnow() - timedelta(seconds=settings.job_lease_seconds)
    stale = db.execute(
        select(Job).where(
            Job.status == "running",
            (Job.claimed_at.is_(None)) | (Job.claimed_at < deadline),
        )
    ).scalars().all()
    for job in stale:
        _recover_stale_job(db, job)
    db.flush()
    return len(stale)


def _recover_stale_job(db: Session, job: Job) -> None:
    error = "Job lease expired while running; worker did not report completion."
    _clear_lease(job)
    if job.attempts < settings.max_job_attempts:
        job.error = error
        job.status = "queued"
        if job.type == "narration":
            shutil.rmtree(
                storage.narration_chunk_dir(job.narration_id), ignore_errors=True
            )
        elif job.type == "clone_prompt" and job.voice_id:
            # Match fail_job: a requeued clone must start clean, so the stale
            # staged .pt from the crashed attempt is dropped and the retry has
            # to upload fresh.
            storage.remove_staged_voice_prompt(job.voice_id)
    else:
        job.status = "failed"
        _mark_failed_owner_object(db, job, error)


def _clear_lease(job: Job) -> None:
    job.claimed_at = None
    job.claim_token = None


# ---------- artifacts ----------
def store_artifact(db: Session, job: Job, field: str, data: bytes) -> None:
    """Persist an uploaded artifact from the worker and update progress."""
    if job.type == "design" and field == "reference_audio":
        storage.write_bytes(storage.voice_preview_rel(job.voice_id), data)
        job.progress = 50
    elif job.type == "clone_prompt" and field == "prompt_pt":
        # Write to a staged path: the live prompt slot (the path referenced by
        # prompt_pt_path / served to narrations) must only ever hold a prompt
        # that has passed full clone completion, so an in-flight attempt never
        # overwrites a previously approved prompt. Promotion happens in
        # complete_job after success.
        storage.write_bytes(storage.voice_prompt_staged_rel(job.voice_id), data)
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
    # Validate the owning parent and the job's required artifact (design preview,
    # clone prompt .pt, or narration chunks) BEFORE the job can be marked
    # succeeded, so a completion whose parent was removed (or whose artifacts are
    # incomplete) fails cleanly instead of leaving a `succeeded` job with a
    # dangling reference. The deletion guards reject removing a voice/narration
    # with a queued or running job, so a missing parent here can only come from a
    # bypass of those guards or manual DB edits; this ordering keeps such states
    # from corrupting job history.
    if job.type == "design":
        voice = db.get(Voice, job.voice_id)
        if voice is None:
            raise RuntimeError("voice record missing")
        if storage.safe_resolve(storage.voice_preview_rel(voice.id)) is None:
            raise RuntimeError("design preview artifact missing")
    elif job.type == "clone_prompt":
        voice = db.get(Voice, job.voice_id)
        if voice is None:
            raise RuntimeError("voice record missing")
        if storage.safe_resolve(storage.voice_prompt_staged_rel(voice.id)) is None:
            raise RuntimeError("clone prompt artifact missing")
    elif job.type == "narration":
        narration = db.get(Narration, job.narration_id)
        if narration is None:
            raise RuntimeError("narration record missing")
        count = _chunk_count(job)
        paths = storage.narration_chunk_paths(narration.id, count)
        existing = [p for p in paths if p.is_file()]
        if len(existing) != count:
            raise RuntimeError(f"expected {count} chunk files, found {len(existing)}")
        # Concatenate to the final audio now: a chunk-read/format failure must
        # surface before the job can be marked succeeded.
        sr, duration = audio.concat_wav_files(
            existing, storage.root() / storage.narration_final_rel(narration.id)
        )

    _clear_lease(job)
    job.status = "succeeded"
    job.progress = 100
    job.result_json = json.dumps({"sample_rate": sample_rate, "durations": durations})

    if job.type == "design":
        if voice.status == "designing":
            voice.status = "preview_ready"
            # The approved reference/prompt are intentionally untouched: a
            # redesign preview lives at the draft preview path and is only
            # promoted to the live reference when the replacement is approved
            # (see approve_voice).
    elif job.type == "clone_prompt":
        if voice.status == "approving":
            # Only now that the clone has fully succeeded are both artifacts
            # promoted into their live slots: the staged .pt becomes the live
            # prompt (Phase #6), and the draft preview the user approved becomes
            # the live reference. A failed/retried attempt leaves the previously
            # approved reference.wav and prompt untouched.
            storage.promote_voice_prompt(voice.id)
            promoted_ref = storage.promote_preview_to_reference(voice.id)
            voice.reference_audio_path = promoted_ref
            voice.status = "approved"
            voice.prompt_pt_path = storage.voice_prompt_rel(voice.id)
    elif job.type == "narration":
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
        # The concatenated final.wav is the authoritative artifact from here on;
        # the per-chunk files are transient intermediates, so drop them once the
        # narration is complete (best-effort, never fatal).
        clear_partial_chunks(narration.id)
    db.flush()


# ---------- failure ----------
def fail_job(db: Session, job: Job, error: str) -> None:
    _clear_lease(job)
    job.error = error[:4000]
    if job.attempts < settings.max_job_attempts:
        job.status = "queued"
        if job.type == "narration":
            shutil.rmtree(storage.narration_chunk_dir(job.narration_id), ignore_errors=True)
        elif job.type == "clone_prompt" and job.voice_id:
            # The staged .pt from this attempt is partial/unverified: drop it so
            # a retry must upload fresh (and complete_job only ever promotes the
            # current attempt's file).
            storage.remove_staged_voice_prompt(job.voice_id)
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
        # No further attempts will run: the intermediate chunk files are no
        # longer needed, so drop them (best-effort, never fatal).
        clear_partial_chunks(job.narration_id)
    elif job.type == "design" and job.voice_id:
        voice = db.get(Voice, job.voice_id)
        if voice is not None and voice.status == "designing":
            # The draft preview from the failed attempt is stale: drop it before
            # restoring the owning voice's previous state (best-effort, never
            # fatal).
            storage.remove_voice_preview(voice.id)
            if voice.reference_audio_path and voice.prompt_pt_path:
                # A failed redesign of an approved voice restores the approved
                # state so its saved reference/prompt keep working.
                voice.status = "approved"
            else:
                voice.status = "draft"
    elif job.type == "clone_prompt" and job.voice_id:
        # No further attempts will run: drop the staged .pt (best-effort, never
        # fatal) so a failed first-time clone leaves no prompt at all and a
        # failed redesign leaves only the previously approved live prompt.
        storage.remove_staged_voice_prompt(job.voice_id)
        voice = db.get(Voice, job.voice_id)
        if voice is not None and voice.status == "approving":
            voice.status = "preview_ready"


# ---------- helpers ----------
def _chunk_count(job: Job) -> int:
    payload = json.loads(job.payload_json)
    return len(payload.get("chunks", []))


def clear_partial_chunks(narration_id: str) -> None:
    shutil.rmtree(storage.narration_chunk_dir(narration_id), ignore_errors=True)
