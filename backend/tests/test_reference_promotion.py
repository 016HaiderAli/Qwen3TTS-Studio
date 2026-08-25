"""Atomic reference-audio promotion tests (Phase 2 #7).

The draft preview audio is only promoted into the live reference slot after a
clone_prompt job completes successfully. While a clone is running or after a
clone fails, the previously approved reference.wav (and its prompt) must remain
intact; a failed first-time clone must create no reference or prompt; and the
preview must stay available for retries. Stale-recovered clone jobs clean their
staged prompt so a retry must upload fresh.
"""
import base64
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


def _create_voice(client, name="My Voice") -> dict:
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
        files={"file": ("a.bin", data, "application/octet-stream")},
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


def _design_to_preview(client, voice_id, wav_bytes) -> dict:
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


def _approve_and_claim_clone(client, voice_id) -> dict:
    resp = client.post(f"/api/voices/{voice_id}/approve")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approving"
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "clone_prompt"
    return claim


def _fail_until_terminal(client, claim):
    for _ in range(get_settings().max_job_attempts):
        _fail(client, claim)
        claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH)
        if claim.status_code == 204:
            break
        claim = claim.json()


def _voice_row(voice_id) -> Voice:
    with SessionLocal() as db:
        return db.get(Voice, voice_id)


def _preview_path(voice_id):
    return storage.root() / storage.voice_preview_rel(voice_id)


def _reference_path(voice_id):
    return storage.root() / storage.voice_reference_rel(voice_id)


def _live_prompt_path(voice_id):
    return storage.root() / storage.voice_prompt_rel(voice_id)


def _staged_prompt_path(voice_id):
    return storage.root() / storage.voice_prompt_staged_rel(voice_id)


def _approved_voice(client, wav_bytes, prompt=b"prompt-A") -> dict:
    voice = _create_voice(client)
    _design_to_preview(client, voice["id"], wav_bytes)
    claim = _approve_and_claim_clone(client, voice["id"])
    _upload(client, claim, "prompt_pt", prompt)
    _complete(client, claim)
    return client.get(f"/api/voices/{voice['id']}").json()


def _expire_claim(job_id) -> None:
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


# ---------- 1. failed redesign clone preserves the approved reference ----------
def test_failed_redesign_preserves_approved_reference(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    first_wav = make_wav_bytes(seconds=1.0)
    voice = _approved_voice(client, first_wav, prompt=b"prompt-A")
    saved_ref_path = _voice_row(voice["id"]).reference_audio_path
    saved_prompt_path = _voice_row(voice["id"]).prompt_pt_path
    assert storage.safe_resolve(saved_ref_path).read_bytes() == first_wav
    assert storage.safe_resolve(saved_prompt_path).read_bytes() == b"prompt-A"

    # Redesign to a new preview B, then approve -> clone job claimed. The clone
    # payload is built from the preview, and the approved reference is untouched.
    new_wav = make_wav_bytes(seconds=2.0)
    voice = _design_to_preview(client, voice["id"], new_wav)
    assert voice["status"] == "preview_ready"
    claim = _approve_and_claim_clone(client, voice["id"])
    assert base64.b64decode(claim["payload"]["ref_audio_b64"]) == new_wav
    assert storage.safe_resolve(saved_ref_path).read_bytes() == first_wav

    # Upload a staged prompt, then fail until terminal.
    _upload(client, claim, "prompt_pt", b"prompt-B-unverified")
    assert _staged_prompt_path(voice["id"]).is_file()
    _fail_until_terminal(client, claim)

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "preview_ready"
    # Approved reference and prompt are fully preserved.
    assert _voice_row(voice["id"]).reference_audio_path == saved_ref_path
    assert storage.safe_resolve(saved_ref_path).read_bytes() == first_wav
    assert _voice_row(voice["id"]).prompt_pt_path == saved_prompt_path
    assert storage.safe_resolve(saved_prompt_path).read_bytes() == b"prompt-A"
    # Staged prompt is dropped; the preview B remains for retry approval.
    assert not _staged_prompt_path(voice["id"]).exists()
    assert _preview_path(voice["id"]).read_bytes() == new_wav


# ---------- 2. successful redesign promotes the preview to reference ----------
def test_successful_redesign_promotes_preview(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    first_wav = make_wav_bytes(seconds=1.0)
    voice = _approved_voice(client, first_wav, prompt=b"prompt-A")

    new_wav = make_wav_bytes(seconds=2.0)
    voice = _design_to_preview(client, voice["id"], new_wav)
    claim = _approve_and_claim_clone(client, voice["id"])

    # While approving, the old reference is still streamed (A, not B).
    audio = client.get(f"/api/files/voices/{voice['id']}/reference")
    assert audio.status_code == 200
    assert audio.content == first_wav

    _upload(client, claim, "prompt_pt", b"prompt-B")
    _complete(client, claim)

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "approved"
    # Reference now holds B; the staged prompt was promoted; preview consumed.
    assert storage.safe_resolve(_voice_row(voice["id"]).reference_audio_path).read_bytes() == new_wav
    assert _voice_row(voice["id"]).prompt_pt_path == storage.voice_prompt_rel(voice["id"])
    assert storage.safe_resolve(_voice_row(voice["id"]).prompt_pt_path).read_bytes() == b"prompt-B"
    assert not _preview_path(voice["id"]).exists()
    assert not _staged_prompt_path(voice["id"]).exists()

    audio = client.get(f"/api/files/voices/{voice['id']}/reference")
    assert audio.content == new_wav


# ---------- 3. failed first-time clone leaves no reference or prompt ----------
def test_first_clone_failure_creates_no_reference_or_prompt(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _create_voice(client)
    _design_to_preview(client, voice["id"], wav)
    claim = _approve_and_claim_clone(client, voice["id"])

    _upload(client, claim, "prompt_pt", b"prompt-unverified")
    assert _staged_prompt_path(voice["id"]).is_file()
    _fail_until_terminal(client, claim)

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "preview_ready"
    row = _voice_row(voice["id"])
    assert row.reference_audio_path is None
    assert row.prompt_pt_path is None
    assert not _reference_path(voice["id"]).exists()
    assert not _live_prompt_path(voice["id"]).exists()
    assert not _staged_prompt_path(voice["id"]).exists()
    assert _preview_path(voice["id"]).read_bytes() == wav


# ---------- 4. successful first-time clone sets reference + prompt ----------
def test_first_clone_success_promotes_reference_and_prompt(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _create_voice(client)
    _design_to_preview(client, voice["id"], wav)
    claim = _approve_and_claim_clone(client, voice["id"])

    # Nothing is live before the clone completes.
    row = _voice_row(voice["id"])
    assert row.reference_audio_path is None
    assert row.prompt_pt_path is None
    assert not _reference_path(voice["id"]).exists()
    assert not _live_prompt_path(voice["id"]).exists()

    _upload(client, claim, "prompt_pt", b"prompt-A")
    _complete(client, claim)

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "approved"
    row = _voice_row(voice["id"])
    assert storage.safe_resolve(row.reference_audio_path).read_bytes() == wav
    assert storage.safe_resolve(row.prompt_pt_path).read_bytes() == b"prompt-A"


# ---------- 5. old reference stays streamable while approving ----------
def test_old_reference_streamable_while_approving(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    first_wav = make_wav_bytes(seconds=1.0)
    voice = _approved_voice(client, first_wav, prompt=b"prompt-A")

    new_wav = make_wav_bytes(seconds=2.0)
    voice = _design_to_preview(client, voice["id"], new_wav)
    _approve_and_claim_clone(client, voice["id"])

    # The reference endpoint serves the old approved A, never the preview B.
    audio = client.get(f"/api/files/voices/{voice['id']}/reference")
    assert audio.status_code == 200
    assert audio.content == first_wav
    # The preview B still exists on disk, ready to be promoted on success.
    assert _preview_path(voice["id"]).read_bytes() == new_wav


# ---------- 6. failed clone then successful retry promotes only on success ----------
def test_failed_clone_then_retry_promotes_on_success(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    first_wav = make_wav_bytes(seconds=1.0)
    voice = _approved_voice(client, first_wav, prompt=b"prompt-A")
    saved_ref_path = _voice_row(voice["id"]).reference_audio_path
    saved_prompt_path = _voice_row(voice["id"]).prompt_pt_path

    new_wav = make_wav_bytes(seconds=2.0)
    voice = _design_to_preview(client, voice["id"], new_wav)
    claim = _approve_and_claim_clone(client, voice["id"])
    _upload(client, claim, "prompt_pt", b"prompt-B-attempt1")
    _fail_until_terminal(client, claim)

    # A is still the reference, B is still the preview, old prompt intact.
    assert storage.safe_resolve(saved_ref_path).read_bytes() == first_wav
    assert _voice_row(voice["id"]).reference_audio_path == saved_ref_path
    assert _voice_row(voice["id"]).prompt_pt_path == saved_prompt_path
    assert storage.safe_resolve(saved_prompt_path).read_bytes() == b"prompt-A"
    assert _preview_path(voice["id"]).read_bytes() == new_wav

    # Retry approval reuses the preserved preview B; succeed this time.
    claim = _approve_and_claim_clone(client, voice["id"])
    assert base64.b64decode(claim["payload"]["ref_audio_b64"]) == new_wav
    _upload(client, claim, "prompt_pt", b"prompt-B")
    _complete(client, claim)

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "approved"
    assert storage.safe_resolve(_voice_row(voice["id"]).reference_audio_path).read_bytes() == new_wav
    assert storage.safe_resolve(_voice_row(voice["id"]).prompt_pt_path).read_bytes() == b"prompt-B"


# ---------- 7. stale-recovered clone cleans its staged prompt ----------
def test_stale_recovered_clone_cleans_staged_prompt(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _create_voice(client)
    _design_to_preview(client, voice["id"], wav)
    claim = _approve_and_claim_clone(client, voice["id"])
    _upload(client, claim, "prompt_pt", b"prompt-stale")
    assert _staged_prompt_path(voice["id"]).is_file()

    # Lease expires -> recovery requeues the job and drops the staged prompt.
    _expire_claim(claim["job_id"])
    assert _recover() == 1
    assert not _staged_prompt_path(voice["id"]).exists()

    # The retry must upload fresh: completing without a staged prompt is rejected.
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "clone_prompt"
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={},
    )
    assert resp.status_code == 422
