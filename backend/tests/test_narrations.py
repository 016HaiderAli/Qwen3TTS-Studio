"""Narration creation/chunking/history tests (worker-side flow covered in E2E)."""
import json

from app import storage
from app.db import SessionLocal
from app.models import Voice


def _approved_voice(owner_id: str, language: str = "English") -> str:
    """Insert an approved voice directly in the DB (prompt artifact present)."""
    with SessionLocal() as db:
        voice = Voice(
            owner_id=owner_id,
            name="Approved Voice",
            language=language,
            description="desc",
            reference_text="ref text",
            status="approved",
            prompt_pt_path=storage.voice_prompt_rel("seed"),
        )
        db.add(voice)
        db.flush()
        voice_id = voice.id
        voice.prompt_pt_path = storage.voice_prompt_rel(voice_id)
        storage.write_bytes(storage.voice_prompt_rel(voice_id), b"mock-prompt")
        db.commit()
    return voice_id


def test_create_narration_requires_approved_voice(client, dev_login):
    dev_login("alice@example.com")
    voice = client.post(
        "/api/voices", json={"name": "V", "language": "English"}
    ).json()
    resp = client.post(
        "/api/narrations",
        json={
            "voice_id": voice["id"],
            "script": "Hello there.",
            "delivery_direction": "Speak slowly and warmly.",
        },
    )
    assert resp.status_code == 409


def test_create_narration_enqueues_job(client, dev_login):
    dev_login("alice@example.com")
    me = client.get("/api/me").json()
    voice_id = _approved_voice(me["id"])

    script = "First sentence. Second sentence.\n\nNew paragraph here."
    resp = client.post(
        "/api/narrations",
        json={
            "voice_id": voice_id,
            "title": "My story",
            "script": script,
            "delivery_direction": "Add pauses after each paragraph.",
            "language": "English",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "queued"
    assert data["chunk_count"] == 1
    assert data["delivery_direction"] == "Add pauses after each paragraph."

    jobs = client.get("/api/jobs").json()
    narration_jobs = [j for j in jobs if j["type"] == "narration"]
    assert narration_jobs and narration_jobs[0]["narration_id"] == data["id"]

    # delivery direction flows into the worker payload
    from app.models import Job

    with SessionLocal() as db:
        job = db.get(Job, narration_jobs[0]["id"])
        payload = json.loads(job.payload_json)
    assert payload["instruct"] == "Add pauses after each paragraph."
    assert payload["language"] == "English"


def test_narration_history_lists_voice_name(client, dev_login):
    dev_login("alice@example.com")
    me = client.get("/api/me").json()
    voice_id = _approved_voice(me["id"])
    client.post(
        "/api/narrations",
        json={"voice_id": voice_id, "script": "Hello there."},
    )
    listing = client.get("/api/narrations").json()
    assert len(listing) == 1
    assert listing[0]["voice_name"] == "Approved Voice"


def test_narration_isolation_between_users(client, dev_login):
    dev_login("alice@example.com")
    me = client.get("/api/me").json()
    voice_id = _approved_voice(me["id"])
    created = client.post(
        "/api/narrations", json={"voice_id": voice_id, "script": "Hi."}
    ).json()

    dev_login("bob@example.com")
    assert client.get(f"/api/narrations/{created['id']}").status_code == 404
    assert client.get(f"/api/files/narrations/{created['id']}/audio").status_code == 404


def test_empty_script_rejected(client, dev_login):
    dev_login("alice@example.com")
    me = client.get("/api/me").json()
    voice_id = _approved_voice(me["id"])
    resp = client.post(
        "/api/narrations", json={"voice_id": voice_id, "script": "   "}
    )
    assert resp.status_code == 422
