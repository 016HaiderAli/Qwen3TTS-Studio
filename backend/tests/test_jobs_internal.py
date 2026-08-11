"""Internal worker API contract tests (poll/artifact/complete/fail)."""
from app import jobs as job_service
from app import storage
from app.db import SessionLocal
from app.models import Voice

WORKER_AUTH = {"Authorization": "Bearer test-worker-token"}


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


def test_narration_chunk_field_validation(client, dev_login):
    dev_login("alice@example.com")
    # enqueue a fake narration job directly (contract-level check)
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
            script="Hi.",
            chunks_json='["Hi."]',
        )
        db.add(narration)
        db.flush()
        job = job_service.enqueue(
            db, user.id, "narration",
            {"chunks": ["Hi."], "narration_id": narration.id},
            voice_id=voice.id, narration_id=narration.id,
        )
        db.commit()
        job_id = job.id

    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["job_id"] == job_id

    resp = client.post(
        f"/internal/jobs/{job_id}/artifact",
        headers=WORKER_AUTH,
        data={"field": "chunk_banana"},
        files={"file": ("c.wav", b"", "application/octet-stream")},
    )
    assert resp.status_code == 422
