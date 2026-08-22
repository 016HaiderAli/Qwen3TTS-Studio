"""Artifact lifecycle tests (Phase 2 #5).

Verifies the transient-vs-authoritative artifact split: narration chunk files
are removed once a narration reaches a terminal state (succeeded or permanently
failed, including stale-job recovery), the draft preview.wav is removed when a
design job fails terminally, and a successful approval moves preview.wav into
reference.wav without leaving a stale copy behind.
"""
from datetime import datetime, timedelta, timezone

from app import jobs as job_service
from app import storage
from app.config import get_settings
from app.db import SessionLocal
from app.models import Job, Voice

WORKER_AUTH = {
    "Authorization": "Bearer test-worker-token",
    "X-Worker-Backend": "mock",
}


def _claim_headers(claim):
    return {**WORKER_AUTH, "X-Job-Claim-Token": claim["claim_token"]}


def _create_voice(client, name="My Voice"):
    resp = client.post(
        "/api/voices",
        json={"name": name, "language": "English", "description": "A calm voice."},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload(client, claim, field, data):
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/artifact",
        headers=_claim_headers(claim),
        data={"field": field},
        files={"file": ("a.wav", data, "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text


def _complete(client, claim, sr=24000, durations=None):
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": sr, "durations": durations or [1.0]},
    )
    assert resp.status_code == 200, resp.text


def _fail(client, claim, error="GPU exploded"):
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/fail",
        headers=_claim_headers(claim),
        json={"error": error},
    )
    assert resp.status_code == 200, resp.text


def _design_to_preview(client, voice_id, wav_bytes):
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
    _upload(client, claim, "reference_audio", wav_bytes)
    _complete(client, claim)
    return client.get(f"/api/voices/{voice_id}").json()


def _approve_to_approved(client, voice_id):
    resp = client.post(f"/api/voices/{voice_id}/approve")
    assert resp.status_code == 200, resp.text
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "clone_prompt"
    _upload(client, claim, "prompt_pt", b"mock-prompt")
    _complete(client, claim)
    return client.get(f"/api/voices/{voice_id}").json()


def _start_narration(client, voice_id):
    resp = client.post(
        "/api/narrations",
        json={"voice_id": voice_id, "script": "Hello there.", "title": "T"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _claim_narration(client):
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "narration"
    return claim


def _upload_all_chunks(client, claim, wav_bytes):
    for i in range(len(claim["payload"]["chunks"])):
        _upload(client, claim, f"chunk_{i}", wav_bytes)


def _fail_until_terminal(client, claim):
    for _ in range(get_settings().max_job_attempts):
        _fail(client, claim)
        claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH)
        if claim.status_code == 204:
            break
        claim = claim.json()


def _chunks_dir(narration_id):
    return storage.root() / f"narrations/{narration_id}/chunks"


def _final_path(narration_id):
    return storage.root() / f"narrations/{narration_id}/final.wav"


def _voice_row(voice_id):
    with SessionLocal() as db:
        return db.get(Voice, voice_id)


def _expire_claim(job_id):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job is not None
        job.claimed_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()


def _recover() -> int:
    with SessionLocal() as db:
        n = job_service.recover_stale_jobs(db)
        db.commit()
        return n


def _approved_voice(client, wav_bytes) -> dict:
    voice = _create_voice(client)
    voice = _design_to_preview(client, voice["id"], wav_bytes)
    return _approve_to_approved(client, voice["id"])


# ---------- 1. successful completion removes the transient chunks ----------
def test_narration_success_removes_chunks(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _approved_voice(client, wav)
    narration = _start_narration(client, voice["id"])
    claim = _claim_narration(client)
    _upload_all_chunks(client, claim, wav)
    assert _chunks_dir(narration["id"]).is_dir()
    _complete(client, claim)

    narration = client.get(f"/api/narrations/{narration['id']}").json()
    assert narration["status"] == "ready"
    assert narration["chunks_done"] == 0
    assert not _chunks_dir(narration["id"]).exists()
    assert _final_path(narration["id"]).is_file()

    audio = client.get(f"/api/files/narrations/{narration['id']}/audio")
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"


# ---------- 2. terminal failure removes the transient chunks ----------
def test_narration_terminal_failure_removes_chunks(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _approved_voice(client, wav)
    narration = _start_narration(client, voice["id"])
    claim = _claim_narration(client)
    _upload_all_chunks(client, claim, wav)
    assert _chunks_dir(narration["id"]).is_dir()

    # First failure -> requeued; chunks are dropped.
    _fail(client, claim)
    assert not _chunks_dir(narration["id"]).exists()

    # Second claim: re-upload, then fail terminally -> chunks dropped again.
    claim = _claim_narration(client)
    _upload_all_chunks(client, claim, wav)
    assert _chunks_dir(narration["id"]).is_dir()
    _fail(client, claim)
    assert client.post("/internal/jobs/poll", headers=WORKER_AUTH).status_code == 204

    assert not _chunks_dir(narration["id"]).exists()
    narration = client.get(f"/api/narrations/{narration['id']}").json()
    assert narration["status"] == "failed"


# ---------- 3. retries start from a clean chunk dir and end clean ----------
def test_narration_requeue_clears_chunks_then_retry_succeeds(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _approved_voice(client, wav)
    narration = _start_narration(client, voice["id"])
    claim = _claim_narration(client)
    _upload_all_chunks(client, claim, wav)
    assert _chunks_dir(narration["id"]).is_dir()

    # Non-terminal failure -> requeued and chunks dropped.
    _fail(client, claim)
    assert not _chunks_dir(narration["id"]).exists()

    # Re-claim, re-upload, complete -> success and chunks dropped again.
    claim = _claim_narration(client)
    _upload_all_chunks(client, claim, wav)
    _complete(client, claim)

    narration = client.get(f"/api/narrations/{narration['id']}").json()
    assert narration["status"] == "ready"
    assert not _chunks_dir(narration["id"]).exists()
    assert _final_path(narration["id"]).is_file()


# ---------- 4. stale-job recovery at max attempts removes the chunks ----------
def test_recovered_stale_narration_terminal_removes_chunks(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _approved_voice(client, wav)
    narration = _start_narration(client, voice["id"])
    claim = _claim_narration(client)
    _upload_all_chunks(client, claim, wav)
    assert _chunks_dir(narration["id"]).is_dir()

    # First staleness: attempts left -> requeued; chunks dropped.
    _expire_claim(claim["job_id"])
    assert _recover() == 1
    assert not _chunks_dir(narration["id"]).exists()

    # Second claim: re-upload, then staleness at max attempts -> terminal fail.
    claim = _claim_narration(client)
    _upload_all_chunks(client, claim, wav)
    assert _chunks_dir(narration["id"]).is_dir()
    _expire_claim(claim["job_id"])
    assert _recover() == 1

    assert not _chunks_dir(narration["id"]).exists()
    narration = client.get(f"/api/narrations/{narration['id']}").json()
    assert narration["status"] == "failed"


# ---------- 5. failed redesign drops the stale draft preview ----------
def test_failed_redesign_removes_stale_preview(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    first_wav = make_wav_bytes(seconds=1.0)
    voice = _approved_voice(client, first_wav)
    saved_ref = _voice_row(voice["id"]).reference_audio_path
    saved_prompt = _voice_row(voice["id"]).prompt_pt_path
    assert saved_ref and saved_prompt

    # Redesign: the draft lands in the preview path, not the saved reference.
    new_wav = make_wav_bytes(seconds=2.0)
    resp = client.post(
        f"/api/voices/{voice['id']}/design",
        json={
            "description": "New voice.",
            "reference_text": "New reference text.",
            "language": "English",
        },
    )
    assert resp.status_code == 200
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "design"
    _upload(client, claim, "reference_audio", new_wav)
    preview = storage.root() / storage.voice_preview_rel(voice["id"])
    assert preview.is_file()
    assert preview.read_bytes() == new_wav

    # Fail until terminal: voice returns to approved, stale preview is removed.
    _fail_until_terminal(client, claim)
    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "approved"
    assert not preview.exists()
    assert storage.safe_resolve(saved_ref).read_bytes() == first_wav
    assert storage.safe_resolve(saved_prompt).is_file()

    audio = client.get(f"/api/files/voices/{voice['id']}/reference")
    assert audio.status_code == 200
    assert audio.content == first_wav


# ---------- 6. failed first-time design leaves no draft preview ----------
def test_failed_first_design_removes_draft_preview(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    resp = client.post(
        f"/api/voices/{voice['id']}/design",
        json={
            "description": "Warm voice.",
            "reference_text": "Sample reference text.",
            "language": "English",
        },
    )
    assert resp.status_code == 200
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "design"
    _upload(client, claim, "reference_audio", make_wav_bytes())
    preview = storage.root() / storage.voice_preview_rel(voice["id"])
    assert preview.is_file()

    _fail_until_terminal(client, claim)
    assert client.get(f"/api/voices/{voice['id']}").json()["status"] == "draft"
    assert not preview.exists()


# ---------- 7. a successful approval moves preview to reference ----------
def test_successful_approval_leaves_no_stale_preview(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _create_voice(client)
    voice = _design_to_preview(client, voice["id"], wav)
    preview = storage.root() / storage.voice_preview_rel(voice["id"])
    assert preview.is_file()
    assert preview.read_bytes() == wav

    voice = _approve_to_approved(client, voice["id"])
    assert voice["status"] == "approved"
    assert not preview.exists()
    reference = storage.root() / storage.voice_reference_rel(voice["id"])
    assert reference.is_file()
    assert reference.read_bytes() == wav
