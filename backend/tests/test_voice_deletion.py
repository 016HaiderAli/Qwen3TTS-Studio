"""Voice/narration deletion policy tests (Phase 2 #3).

Deletion is an explicit cascade: deleting a voice removes its narrations, every
job referencing the voice (design/clone/narration) or its narrations, and all
voice + narration artifacts on disk. Deletion is rejected with 409 while any
queued/running job references the voice (directly or via its narrations) or
while the voice is designing/approving.
"""
from sqlalchemy import text

from app import storage
from app.db import engine

WORKER_AUTH = {
    "Authorization": "Bearer test-worker-token",
    "X-Worker-Backend": "mock",
}


def _claim_headers(claim):
    return {**WORKER_AUTH, "X-Job-Claim-Token": claim["claim_token"]}


def _create_voice(client, name="My Voice") -> dict:
    resp = client.post(
        "/api/voices",
        json={"name": name, "language": "English", "description": "A calm voice."},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _design_to_preview(client, voice_id, wav_bytes) -> None:
    resp = client.post(
        f"/api/voices/{voice_id}/design",
        json={
            "description": "Warm voice.",
            "reference_text": "Sample reference text.",
            "language": "English",
        },
    )
    assert resp.status_code == 200, resp.text
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "design"
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/artifact",
        headers=_claim_headers(claim),
        data={"field": "reference_audio"},
        files={"file": ("a.wav", wav_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 200, resp.text


def _approve_to_approved(client, voice_id) -> None:
    resp = client.post(f"/api/voices/{voice_id}/approve")
    assert resp.status_code == 200, resp.text
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "clone_prompt"
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/artifact",
        headers=_claim_headers(claim),
        data={"field": "prompt_pt"},
        files={"file": ("prompt.pt", b"mock-prompt", "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={},
    )
    assert resp.status_code == 200, resp.text


def _approved_voice(client, wav_bytes) -> dict:
    voice = _create_voice(client)
    _design_to_preview(client, voice["id"], wav_bytes)
    _approve_to_approved(client, voice["id"])
    return client.get(f"/api/voices/{voice['id']}").json()


def _create_and_finish_narration(client, voice_id, wav_bytes) -> dict:
    resp = client.post(
        "/api/narrations",
        json={"voice_id": voice_id, "script": "Hello there.", "title": "T"},
    )
    assert resp.status_code == 201, resp.text
    narration = resp.json()
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "narration"
    assert claim["payload"]["narration_id"] == narration["id"]
    for i in range(len(claim["payload"]["chunks"])):
        resp = client.post(
            f"/internal/jobs/{claim['job_id']}/artifact",
            headers=_claim_headers(claim),
            data={"field": f"chunk_{i}"},
            files={"file": (f"chunk_{i}.wav", wav_bytes, "application/octet-stream")},
        )
        assert resp.status_code == 200, resp.text
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0] * len(claim["payload"]["chunks"])},
    )
    assert resp.status_code == 200, resp.text
    return narration


def _count(table: str) -> int:
    with engine.connect() as conn:
        extra = " WHERE id != '00000000-0000-0000-0000-000000000000'" if table == "voices" else ""
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}{extra}")).scalar()


def test_voice_delete_cascades_narrations_jobs_and_artifacts(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _approved_voice(client, wav)
    narration = _create_and_finish_narration(client, voice["id"], wav)

    voice_dir = storage.root() / f"voices/{voice['id']}"
    narration_dir = storage.root() / f"narrations/{narration['id']}"
    assert (voice_dir / "reference.wav").is_file()
    assert (voice_dir / "voice_clone_prompt.pt").is_file()
    assert not (narration_dir / "chunks").exists()
    assert (narration_dir / "final.wav").is_file()

    resp = client.delete(f"/api/voices/{voice['id']}")
    assert resp.status_code == 204

    assert client.get("/api/voices").json() == []
    assert client.get("/api/narrations").json() == []
    assert client.get("/api/jobs").json() == []
    assert _count("voices") == 0
    assert _count("narrations") == 0
    assert _count("jobs") == 0
    assert not voice_dir.exists()
    assert not narration_dir.exists()


def test_voice_delete_409_while_design_job_queued(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    resp = client.post(
        f"/api/voices/{voice['id']}/design",
        json={"description": "x", "reference_text": "y", "language": "English"},
    )
    assert resp.status_code == 200
    resp = client.delete(f"/api/voices/{voice['id']}")
    assert resp.status_code == 409
    assert client.get(f"/api/voices/{voice['id']}").json()["status"] == "designing"


def test_voice_delete_409_while_design_job_running(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    resp = client.post(
        f"/api/voices/{voice['id']}/design",
        json={"description": "x", "reference_text": "y", "language": "English"},
    )
    assert resp.status_code == 200
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "design"
    resp = client.delete(f"/api/voices/{voice['id']}")
    assert resp.status_code == 409
    # The worker is never orphaned: it can still finish the job.
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/artifact",
        headers=_claim_headers(claim),
        data={"field": "reference_audio"},
        files={"file": ("a.wav", make_wav_bytes(), "application/octet-stream")},
    )
    assert resp.status_code == 200
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 200


def test_voice_delete_409_while_approving(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design_to_preview(client, voice["id"], make_wav_bytes())
    resp = client.post(f"/api/voices/{voice['id']}/approve")
    assert resp.status_code == 200
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "clone_prompt"
    resp = client.delete(f"/api/voices/{voice['id']}")
    assert resp.status_code == 409
    assert client.get(f"/api/voices/{voice['id']}").json()["status"] == "approving"


def test_voice_delete_409_while_narration_queued_or_running(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _approved_voice(client, wav)
    resp = client.post(
        "/api/narrations", json={"voice_id": voice["id"], "script": "Hello there."}
    )
    assert resp.status_code == 201
    assert client.delete(f"/api/voices/{voice['id']}").status_code == 409
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "narration"
    assert client.delete(f"/api/voices/{voice['id']}").status_code == 409
    assert client.get(f"/api/voices/{voice['id']}").status_code == 200


def test_narration_delete_409_while_queued_or_running(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _approved_voice(client, wav)
    resp = client.post(
        "/api/narrations", json={"voice_id": voice["id"], "script": "Hello there."}
    )
    narration = resp.json()
    assert client.delete(f"/api/narrations/{narration['id']}").status_code == 409
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "narration"
    assert client.delete(f"/api/narrations/{narration['id']}").status_code == 409
    # The worker can still finish the narration.
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/artifact",
        headers=_claim_headers(claim),
        data={"field": "chunk_0"},
        files={"file": ("c.wav", wav, "application/octet-stream")},
    )
    assert resp.status_code == 200
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 200


def test_narration_delete_removes_narration_and_its_jobs(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _approved_voice(client, wav)
    narration = _create_and_finish_narration(client, voice["id"], wav)
    narration_dir = storage.root() / f"narrations/{narration['id']}"
    assert (narration_dir / "final.wav").is_file()

    resp = client.delete(f"/api/narrations/{narration['id']}")
    assert resp.status_code == 204
    assert client.get(f"/api/narrations/{narration['id']}").status_code == 404
    assert not narration_dir.exists()
    jobs = client.get("/api/jobs").json()
    assert all(j["type"] != "narration" for j in jobs)
    assert client.get(f"/api/voices/{voice['id']}").status_code == 200


def test_sqlite_foreign_keys_enforced():
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_voice_delete_ownership_preserved(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    dev_login("bob@example.com")
    assert client.delete(f"/api/voices/{voice['id']}").status_code == 404
