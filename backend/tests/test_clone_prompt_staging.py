"""Clone-prompt staged-write tests (Phase 2 #6).

The worker uploads the clone `.pt` to a staged path, and it is only promoted
into the live prompt slot (the path referenced by ``prompt_pt_path``) after a
clone_prompt job completes successfully. A failed or retried clone must never
overwrite a previously approved prompt; a first-time failed clone must leave no
live or staged prompt behind.
"""
from app import storage
from app.config import get_settings
from app.db import SessionLocal
from app.models import Voice

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


def _approve_and_claim_clone(client, voice_id):
    resp = client.post(f"/api/voices/{voice_id}/approve")
    assert resp.status_code == 200, resp.text
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


def _voice_row(voice_id):
    with SessionLocal() as db:
        return db.get(Voice, voice_id)


def _staged_path(voice_id):
    return storage.root() / storage.voice_prompt_staged_rel(voice_id)


def _live_path(voice_id):
    return storage.root() / storage.voice_prompt_rel(voice_id)


def _approved_voice(client, wav_bytes, prompt=b"prompt-v1") -> dict:
    voice = _create_voice(client)
    _design_to_preview(client, voice["id"], wav_bytes)
    claim = _approve_and_claim_clone(client, voice["id"])
    _upload(client, claim, "prompt_pt", prompt)
    _complete(client, claim)
    return client.get(f"/api/voices/{voice['id']}").json()


# ---------- 1. failed redesign clone preserves the approved prompt ----------
def test_redesign_clone_terminal_failure_preserves_live_prompt(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    first_wav = make_wav_bytes(seconds=1.0)
    voice = _approved_voice(client, first_wav, prompt=b"prompt-v1")
    saved_prompt_path = _voice_row(voice["id"]).prompt_pt_path
    assert storage.safe_resolve(saved_prompt_path).read_bytes() == b"prompt-v1"

    # Redesign: new draft preview, then approve -> clone job claimed.
    new_wav = make_wav_bytes(seconds=2.0)
    voice = _design_to_preview(client, voice["id"], new_wav)
    assert voice["status"] == "preview_ready"
    claim = _approve_and_claim_clone(client, voice["id"])

    # Worker uploads a new prompt to the STAGED path; the live slot is untouched.
    _upload(client, claim, "prompt_pt", b"prompt-v2-unverified")
    assert _staged_path(voice["id"]).is_file()
    assert _staged_path(voice["id"]).read_bytes() == b"prompt-v2-unverified"
    assert storage.safe_resolve(saved_prompt_path).read_bytes() == b"prompt-v1"

    # Fail until terminal: staged file is dropped, approved prompt is preserved.
    _fail_until_terminal(client, claim)
    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "preview_ready"
    assert not _staged_path(voice["id"]).exists()
    assert not _live_path(voice["id"]).exists() or _live_path(voice["id"]).read_bytes() == b"prompt-v1"
    assert _voice_row(voice["id"]).prompt_pt_path == saved_prompt_path
    assert storage.safe_resolve(saved_prompt_path).read_bytes() == b"prompt-v1"


# ---------- 2. successful redesign clone promotes the staged prompt ----------
def test_redesign_clone_success_promotes_staged_prompt(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    first_wav = make_wav_bytes(seconds=1.0)
    voice = _approved_voice(client, first_wav, prompt=b"prompt-v1")

    # Redesign: new draft preview, then approve -> clone job claimed.
    new_wav = make_wav_bytes(seconds=2.0)
    voice = _design_to_preview(client, voice["id"], new_wav)
    claim = _approve_and_claim_clone(client, voice["id"])

    # Upload to staged, then complete: staged promoted into the live slot.
    _upload(client, claim, "prompt_pt", b"prompt-v2")
    assert _live_path(voice["id"]).read_bytes() == b"prompt-v1"
    _complete(client, claim)

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "approved"
    assert not _staged_path(voice["id"]).exists()
    assert _live_path(voice["id"]).read_bytes() == b"prompt-v2"
    assert _voice_row(voice["id"]).prompt_pt_path == storage.voice_prompt_rel(voice["id"])


# ---------- 3. failed first-time clone leaves no live or staged prompt ----------
def test_first_clone_terminal_failure_leaves_no_prompt(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _create_voice(client)
    _design_to_preview(client, voice["id"], wav)
    claim = _approve_and_claim_clone(client, voice["id"])

    _upload(client, claim, "prompt_pt", b"prompt-unverified")
    assert _staged_path(voice["id"]).is_file()

    _fail_until_terminal(client, claim)
    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "preview_ready"
    assert not _staged_path(voice["id"]).exists()
    assert not _live_path(voice["id"]).exists()
    assert _voice_row(voice["id"]).prompt_pt_path is None


# ---------- 4. successful first-time clone promotes the staged prompt ----------
def test_first_clone_success_promotes_staged_prompt(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _create_voice(client)
    _design_to_preview(client, voice["id"], wav)
    claim = _approve_and_claim_clone(client, voice["id"])

    _upload(client, claim, "prompt_pt", b"prompt-v1")
    assert _staged_path(voice["id"]).is_file()
    assert not _live_path(voice["id"]).exists()
    _complete(client, claim)

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "approved"
    assert not _staged_path(voice["id"]).exists()
    assert _live_path(voice["id"]).read_bytes() == b"prompt-v1"
    assert _voice_row(voice["id"]).prompt_pt_path == storage.voice_prompt_rel(voice["id"])


# ---------- 5. retry clears the staged file, then promotes on success ----------
def test_clone_retry_clears_staged_then_promotes_on_success(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    first_wav = make_wav_bytes(seconds=1.0)
    voice = _approved_voice(client, first_wav, prompt=b"prompt-v1")
    saved_prompt_path = _voice_row(voice["id"]).prompt_pt_path

    # Redesign, approve -> clone job claimed; upload a staged prompt, then fail.
    new_wav = make_wav_bytes(seconds=2.0)
    voice = _design_to_preview(client, voice["id"], new_wav)
    claim = _approve_and_claim_clone(client, voice["id"])
    _upload(client, claim, "prompt_pt", b"prompt-v2-attempt1")
    assert _staged_path(voice["id"]).is_file()

    # Non-terminal failure -> requeued and the staged file is dropped; the
    # previously approved live prompt is preserved.
    _fail(client, claim)
    assert not _staged_path(voice["id"]).exists()
    assert storage.safe_resolve(saved_prompt_path).read_bytes() == b"prompt-v1"

    # Re-claim the same clone job, re-upload, complete -> promoted.
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "clone_prompt"
    _upload(client, claim, "prompt_pt", b"prompt-v2")
    assert not _live_path(voice["id"]).exists() or _live_path(voice["id"]).read_bytes() == b"prompt-v1"
    _complete(client, claim)

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "approved"
    assert not _staged_path(voice["id"]).exists()
    assert _live_path(voice["id"]).read_bytes() == b"prompt-v2"
    assert _voice_row(voice["id"]).prompt_pt_path == storage.voice_prompt_rel(voice["id"])
