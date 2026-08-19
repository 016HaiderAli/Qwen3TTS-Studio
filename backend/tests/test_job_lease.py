"""Job lease + stale-job recovery tests.

Covers the lease/recovery foundation: claimed_at stamping, lease expiry,
safe requeue, attempt limits, terminal failure releasing the owning
voice/narration, and claim-token ownership that stops a superseded worker
from corrupting a recovered/reclaimed job.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app import jobs as job_service
from app import storage
from app.config import get_settings
from app.db import SessionLocal
from app.models import Job, Narration, User, Voice

WORKER_AUTH = {
    "Authorization": "Bearer test-worker-token",
    "X-Worker-Backend": "mock",
}
QWEN_AUTH = {
    "Authorization": "Bearer test-worker-token",
    "X-Worker-Backend": "qwen",
}


def _claim_headers(claim, backend=WORKER_AUTH):
    return {**backend, "X-Job-Claim-Token": claim["claim_token"]}


def _create_voice(client, name="V"):
    resp = client.post("/api/voices", json={"name": name, "language": "English"})
    assert resp.status_code == 201
    return resp.json()


def _design(client, voice_id):
    return client.post(
        f"/api/voices/{voice_id}/design",
        json={
            "description": "Warm voice.",
            "reference_text": "Sample reference text.",
            "language": "English",
        },
    )


def _claim(client, headers=WORKER_AUTH) -> dict:
    resp = client.post("/internal/jobs/poll", headers=headers)
    assert resp.status_code == 200
    return resp.json()


def _expire_claim(job_id: str, hours: float = 1.0) -> None:
    """Backdate a running job's claimed_at so its lease is expired."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        job.claimed_at = datetime.now(timezone.utc) - timedelta(hours=hours)
        db.commit()


def _recover() -> int:
    with SessionLocal() as db:
        n = job_service.recover_stale_jobs(db)
        db.commit()
        return n


def _job_row(job_id: str) -> Job:
    with SessionLocal() as db:
        return db.get(Job, job_id)


def _enqueue_narration_job(dev_login):
    """Create an approved voice + narration and a queued narration job."""
    dev_login("alice@example.com")
    with SessionLocal() as db:
        user = db.execute(
            select(User).where(User.email == "alice@example.com")
        ).scalar_one()
        voice = Voice(
            owner_id=user.id, name="V", status="approved",
            prompt_pt_path=storage.voice_prompt_rel("x"),
        )
        db.add(voice)
        db.flush()
        narration = Narration(
            owner_id=user.id,
            voice_id=voice.id,
            script="Hi.",
            chunks_json=str(["Hi."]),
        )
        db.add(narration)
        db.flush()
        job = job_service.enqueue(
            db, user.id, "narration",
            {"chunks": ["Hi."], "narration_id": narration.id},
            voice_id=voice.id, narration_id=narration.id,
        )
        db.commit()
        return job.id, narration.id, voice.id


# ---------- 1. claim stamps the lease ----------
def test_claimed_job_has_claimed_at_and_claim_token(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])

    claim = _claim(client)
    assert claim["claim_token"]
    with SessionLocal() as db:
        job = db.get(Job, claim["job_id"])
        assert job.status == "running"
        assert job.claimed_at is not None
        assert job.claim_token == claim["claim_token"]
        assert job.attempts == 1


# ---------- 2. a fresh running job is not stale ----------
def test_fresh_running_job_is_not_stale(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])
    claim = _claim(client)

    assert _recover() == 0
    job = _job_row(claim["job_id"])
    assert job.status == "running"
    assert job.claim_token == claim["claim_token"]


# ---------- 3. an expired running job is recovered (requeued) ----------
def test_expired_running_job_is_recovered(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])
    claim = _claim(client)
    job_id = claim["job_id"]

    _expire_claim(job_id)
    assert _recover() == 1

    job = _job_row(job_id)
    assert job.status == "queued"
    assert job.claimed_at is None
    assert job.claim_token is None
    assert "lease" in job.error


# ---------- 4. a recovered job can be claimed again ----------
def test_recovered_job_can_be_claimed_again(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])
    claim = _claim(client)
    job_id = claim["job_id"]

    _expire_claim(job_id)
    _recover()

    claim2 = _claim(client)
    assert claim2["job_id"] == job_id
    assert claim2["claim_token"] != claim["claim_token"]
    job = _job_row(job_id)
    assert job.status == "running"
    assert job.attempts == 2


# ---------- 5 & 6. attempt limits respected; terminal failure at max ----------
def test_stale_job_at_max_attempts_becomes_terminal_failure(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])

    # First staleness: attempts left -> requeued.
    claim = _claim(client)
    job_id = claim["job_id"]
    _expire_claim(job_id)
    assert _recover() == 1
    assert _job_row(job_id).status == "queued"

    # Second claim + staleness: attempts exhausted -> terminal failure.
    claim2 = _claim(client)
    assert claim2["job_id"] == job_id
    _expire_claim(job_id)
    assert _recover() == 1

    job = _job_row(job_id)
    assert job.status == "failed"
    assert job.attempts == get_settings().max_job_attempts
    assert "lease" in job.error

    # Nothing left to claim.
    assert client.post("/internal/jobs/poll", headers=WORKER_AUTH).status_code == 204


# ---------- 7. owning voice/narration is released on terminal stale failure ---
def test_stale_terminal_failure_unsticks_voice(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])
    assert client.get(f"/api/voices/{voice['id']}").json()["status"] == "designing"

    for _ in range(get_settings().max_job_attempts):
        claim = _claim(client)
        _expire_claim(claim["job_id"])
        _recover()

    assert client.post("/internal/jobs/poll", headers=WORKER_AUTH).status_code == 204
    assert client.get(f"/api/voices/{voice['id']}").json()["status"] == "draft"


def test_stale_terminal_failure_unsticks_narration(client, dev_login):
    job_id, narration_id, voice_id = _enqueue_narration_job(dev_login)

    for _ in range(get_settings().max_job_attempts):
        claim = _claim(client)
        assert claim["job_id"] == job_id
        _expire_claim(job_id)
        _recover()

    assert client.post("/internal/jobs/poll", headers=WORKER_AUTH).status_code == 204
    with SessionLocal() as db:
        narration = db.get(Narration, narration_id)
        assert narration.status == "failed"
        assert "lease" in narration.error


# ---------- 8. a late complete cannot overwrite the recovered job ----------
def test_late_complete_cannot_overwrite_recovered_job(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])

    worker_a = _claim(client)  # original worker
    job_id = worker_a["job_id"]
    _expire_claim(job_id)
    _recover()

    worker_b = _claim(client)  # recovery worker
    assert worker_b["job_id"] == job_id

    # Worker A tries to complete with its stale token -> rejected.
    late = client.post(
        f"/internal/jobs/{job_id}/complete",
        headers=_claim_headers(worker_a),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert late.status_code == 409

    # The job is untouched and still owned by worker B.
    job = _job_row(job_id)
    assert job.status == "running"
    assert job.claim_token == worker_b["claim_token"]

    # Worker B completes normally.
    upload = client.post(
        f"/internal/jobs/{job_id}/artifact",
        headers=_claim_headers(worker_b),
        data={"field": "reference_audio"},
        files={"file": ("ref.wav", make_wav_bytes(), "application/octet-stream")},
    )
    assert upload.status_code == 200
    done = client.post(
        f"/internal/jobs/{job_id}/complete",
        headers=_claim_headers(worker_b),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert done.status_code == 200
    assert _job_row(job_id).status == "succeeded"
    assert client.get(f"/api/voices/{voice['id']}").json()["status"] == "preview_ready"


# ---------- 9. a late fail cannot corrupt the recovered job ----------
def test_late_fail_cannot_corrupt_recovered_job(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])

    worker_a = _claim(client)
    job_id = worker_a["job_id"]
    _expire_claim(job_id)
    _recover()

    worker_b = _claim(client)
    assert worker_b["job_id"] == job_id

    # Worker A's late fail is rejected and cannot re-queue or fail the job.
    late = client.post(
        f"/internal/jobs/{job_id}/fail",
        headers=_claim_headers(worker_a),
        json={"error": "late failure"},
    )
    assert late.status_code == 409

    job = _job_row(job_id)
    assert job.status == "running"
    assert job.claim_token == worker_b["claim_token"]

    # Worker B completes successfully.
    done = client.post(
        f"/internal/jobs/{job_id}/complete",
        headers=_claim_headers(worker_b),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert done.status_code == 200
    assert _job_row(job_id).status == "succeeded"


def test_missing_or_wrong_claim_token_rejected(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])
    claim = _claim(client)
    job_id = claim["job_id"]

    # No token header.
    resp = client.post(
        f"/internal/jobs/{job_id}/complete",
        headers=WORKER_AUTH,
        json={},
    )
    assert resp.status_code == 409

    # A valid-shaped but wrong token.
    resp = client.post(
        f"/internal/jobs/{job_id}/complete",
        headers={**WORKER_AUTH, "X-Job-Claim-Token": "not-the-token"},
        json={},
    )
    assert resp.status_code == 409
    assert _job_row(job_id).status == "running"


# ---------- 10. corrected preview config: mock tags mock jobs ----------
def test_start_sh_tags_preview_jobs_for_mock_worker():
    """Regression: the documented mock preview must tag web-tier jobs 'mock'
    (via DEFAULT_JOB_BACKEND defaulting to WORKER_BACKEND) so the mock worker
    can claim them. Without this, mock-started previews never process a job."""
    start_sh = Path(__file__).resolve().parent.parent.parent / "start.sh"
    text = start_sh.read_text()
    assert "${DEFAULT_JOB_BACKEND:-$WORKER_BACKEND}" in text
    assert 'WORKER_BACKEND="${WORKER_BACKEND:-mock}"' in text


def test_mock_default_backend_jobs_claimable_only_by_mock(client, dev_login):
    """Under the corrected preview configuration (DEFAULT_JOB_BACKEND=mock),
    web-tier jobs are claimable by the mock worker and not by the qwen worker."""
    assert get_settings().default_job_backend == "mock"
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])

    claim = _claim(client)
    assert claim["type"] == "design"
    with SessionLocal() as db:
        job = db.get(Job, claim["job_id"])
        assert job.required_backend == "mock"


# ---------- 11. capability gate remains strict in both directions ----------
def test_qwen_worker_cannot_claim_mock_job(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])

    # qwen worker finds nothing...
    assert client.post("/internal/jobs/poll", headers=QWEN_AUTH).status_code == 204
    # ...and the mock worker claims it.
    claim = _claim(client)
    assert claim["type"] == "design"


def test_mock_worker_cannot_claim_qwen_job(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    with SessionLocal() as db:
        user = db.execute(
            select(User).where(User.email == "alice@example.com")
        ).scalar_one()
        job_service.enqueue(
            db,
            user.id,
            "design",
            {"voice_id": voice["id"]},
            voice_id=voice["id"],
            required_backend="qwen",
        )
        db.commit()

    assert client.post("/internal/jobs/poll", headers=WORKER_AUTH).status_code == 204
    claim = client.post("/internal/jobs/poll", headers=QWEN_AUTH).json()
    assert claim["type"] == "design"
