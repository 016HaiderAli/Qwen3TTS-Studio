"""Internal worker API contract tests (poll/artifact/complete/fail)."""
from app import jobs as job_service
from app import storage
from app.db import SessionLocal
from app.models import Narration, Voice

WORKER_AUTH = {
    "Authorization": "Bearer test-worker-token",
    "X-Worker-Backend": "mock",
}
QWEN_AUTH = {
    "Authorization": "Bearer test-worker-token",
    "X-Worker-Backend": "qwen",
}


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


def test_poll_requires_worker_token(client):
    resp = client.post("/internal/jobs/poll")
    assert resp.status_code == 401
    resp = client.post(
        "/internal/jobs/poll",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert resp.status_code == 401


def test_internal_poll_reachable_with_worker_token(client, dev_login):
    """POST /internal/jobs/poll is reachable (registered route + auth) and returns a claim."""
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])
    resp = client.post("/internal/jobs/poll", headers=WORKER_AUTH)
    assert resp.status_code == 200
    claim = resp.json()
    assert claim["job_id"]
    assert claim["type"] == "design"


def test_internal_poll_unconfigured_returns_503_not_404(client, monkeypatch):
    """Without WORKER_TOKEN the route still exists but is disabled with 503, so
    a request never looks like the route is missing (the misleading 404)."""
    from app import deps

    monkeypatch.setattr(deps.settings, "worker_token", "")
    resp = client.post("/internal/jobs/poll")
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"]


def test_poll_requires_worker_backend_header(client, dev_login):
    """A worker that does not declare a backend capability cannot claim jobs."""
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])
    resp = client.post("/internal/jobs/poll", headers={"Authorization": "Bearer test-worker-token"})
    assert resp.status_code == 403
    # The job is still claimable by a worker that declares the matching backend.
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "design"


def test_mock_worker_cannot_claim_qwen_job(client, dev_login):
    """A job tagged for the real qwen worker cannot be claimed by a mock worker."""
    dev_login("alice@example.com")
    voice = _create_voice(client)
    with SessionLocal() as db:
        from sqlalchemy import select

        from app.models import User

        user = db.execute(
            select(User).where(User.email == "alice@example.com")
        ).scalar_one()
        job_service.enqueue(
            db,
            user.id,
            "design",
            {
                "voice_id": voice["id"],
                "language": "English",
                "instruct": "Warm voice.",
                "text": "Sample reference text.",
            },
            voice_id=voice["id"],
            required_backend="qwen",
        )
        db.commit()

    # mock worker finds nothing...
    assert client.post("/internal/jobs/poll", headers=WORKER_AUTH).status_code == 204
    # ...but the qwen worker claims it.
    claim = client.post("/internal/jobs/poll", headers=QWEN_AUTH).json()
    assert claim["type"] == "design"


def test_mock_worker_cannot_complete_qwen_job(client, dev_login):
    """Even if a mock worker learns a qwen job id, it cannot upload/complete it."""
    dev_login("alice@example.com")
    voice = _create_voice(client)
    with SessionLocal() as db:
        from sqlalchemy import select

        from app.models import User

        user = db.execute(
            select(User).where(User.email == "alice@example.com")
        ).scalar_one()
        job = job_service.enqueue(
            db,
            user.id,
            "design",
            {"voice_id": voice["id"]},
            voice_id=voice["id"],
            required_backend="qwen",
        )
        db.commit()
        job_id = job.id

    # qwen worker claims it (moves to running)
    claim = client.post("/internal/jobs/poll", headers=QWEN_AUTH).json()
    assert claim["job_id"] == job_id

    # a mock worker cannot upload or complete the qwen job
    upload = client.post(
        f"/internal/jobs/{job_id}/artifact",
        headers=WORKER_AUTH,
        data={"field": "reference_audio"},
        files={"file": ("a.wav", b"x", "application/octet-stream")},
    )
    assert upload.status_code == 403
    complete = client.post(
        f"/internal/jobs/{job_id}/complete", headers=WORKER_AUTH, json={}
    )
    assert complete.status_code == 403


def test_dev_worker_token_fallback_config():
    """Dev-login mode defaults WORKER_TOKEN to the documented dev token; non-dev
    mode still requires an explicit token (fails closed)."""
    from app.config import Settings

    dev = Settings(dev_login=True, worker_token="")
    assert dev.worker_token == "dev-worker-token"

    prod = Settings(dev_login=False, worker_token="")
    assert prod.worker_token == ""


def test_design_job_lifecycle(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])

    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "design"
    assert claim["payload"]["voice_id"] == voice["id"]
    assert claim["payload"]["language"] == "English"

    # invalid WAV upload rejected
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/artifact",
        headers=WORKER_AUTH,
        data={"field": "reference_audio"},
        files={"file": ("bad.wav", b"garbage", "application/octet-stream")},
    )
    assert resp.status_code == 422

    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/artifact",
        headers=WORKER_AUTH,
        data={"field": "reference_audio"},
        files={"file": ("ref.wav", make_wav_bytes(), "application/octet-stream")},
    )
    assert resp.status_code == 200

    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=WORKER_AUTH,
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 200

    voice_resp = client.get(f"/api/voices/{voice['id']}").json()
    assert voice_resp["status"] == "preview_ready"

    # reference file is now streamable
    audio = client.get(f"/api/files/voices/{voice['id']}/reference")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"


def test_fail_retries_then_marks_failed(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])

    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/fail",
        headers=WORKER_AUTH,
        json={"error": "GPU exploded"},
    )
    assert resp.status_code == 200
    # first failure -> requeued for retry
    claim2 = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim2 is not None
    resp = client.post(
        f"/internal/jobs/{claim2['job_id']}/fail",
        headers=WORKER_AUTH,
        json={"error": "still broken"},
    )
    assert resp.status_code == 200
    assert client.post("/internal/jobs/poll", headers=WORKER_AUTH).status_code == 204
    voice_resp = client.get(f"/api/voices/{voice['id']}").json()
    assert voice_resp["status"] == "draft"


def test_complete_rejects_non_running_job(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design(client, voice["id"])
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=WORKER_AUTH,
        json={},
    )
    # completing again should 409
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=WORKER_AUTH,
        json={},
    )
    assert resp.status_code == 409


def _enqueue_narration_job(dev_login, script="Hi.", chunks=("Hi.",)):
    """Create an approved voice + narration and a queued narration job."""
    dev_login("alice@example.com")
    with SessionLocal() as db:
        from sqlalchemy import select

        from app.models import Job, Narration, User

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
            script=script,
            chunks_json=str(list(chunks)),
        )
        db.add(narration)
        db.flush()
        job = job_service.enqueue(
            db, user.id, "narration",
            {"chunks": list(chunks), "narration_id": narration.id},
            voice_id=voice.id, narration_id=narration.id,
        )
        db.commit()
        return job.id, narration.id


def test_narration_chunk_field_validation(client, dev_login):
    job_id, _ = _enqueue_narration_job(dev_login)
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["job_id"] == job_id

    resp = client.post(
        f"/internal/jobs/{job_id}/artifact",
        headers=WORKER_AUTH,
        data={"field": "chunk_banana"},
        files={"file": ("c.wav", b"", "application/octet-stream")},
    )
    assert resp.status_code == 422


def test_narration_complete_uses_wav_sample_rate_as_authoritative(
    client, dev_login, make_wav_bytes
):
    """The final narration's sample rate is parsed from the actual WAV chunks,
    never trusted from the worker's reported value."""
    job_id, narration_id = _enqueue_narration_job(dev_login)
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["job_id"] == job_id

    chunk_wav = make_wav_bytes(sr=16000, seconds=0.5)
    resp = client.post(
        f"/internal/jobs/{job_id}/artifact",
        headers=WORKER_AUTH,
        data={"field": "chunk_0"},
        files={"file": ("c.wav", chunk_wav, "application/octet-stream")},
    )
    assert resp.status_code == 200

    # The worker claims 24000 Hz, but the actual artifact is 16000 Hz.
    resp = client.post(
        f"/internal/jobs/{job_id}/complete",
        headers=WORKER_AUTH,
        json={"sample_rate": 24000, "durations": [0.5]},
    )
    assert resp.status_code == 200

    with SessionLocal() as db:
        narration = db.get(Narration, narration_id)
        assert narration.status == "ready"
        assert narration.sample_rate == 16000
        assert narration.duration_sec == 0.5

    # The final file is playable at the authoritative rate.
    audio = client.get(f"/api/files/narrations/{narration_id}/audio")
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"
    import struct

    assert struct.unpack("<I", audio.content[24:28])[0] == 16000
