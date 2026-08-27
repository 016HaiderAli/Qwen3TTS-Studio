"""Atomic clone-promotion tests (Phase 2 #8).

The two live-slot promotions that happen when a clone_prompt job completes (the
draft preview -> live reference, and the staged .pt -> live prompt) are
irreversible os.replace moves. This phase closes the remaining atomicity gaps:

1. If the draft preview is missing at completion (external/manual interference),
   completion must fail cleanly BEFORE any live slot is mutated, so the
   previously approved prompt and reference are never destroyed.
2. The reference is promoted before the prompt, so a crash or exception between
   the two promotions preserves the previously approved (narration-critical)
   prompt rather than the regenerable reference audio.
"""
import base64
from pathlib import Path

import pytest

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


def _preview_path(voice_id) -> Path:
    return storage.root() / storage.voice_preview_rel(voice_id)


def _reference_path(voice_id) -> Path:
    return storage.root() / storage.voice_reference_rel(voice_id)


def _live_prompt_path(voice_id) -> Path:
    return storage.root() / storage.voice_prompt_rel(voice_id)


def _staged_prompt_path(voice_id) -> Path:
    return storage.root() / storage.voice_prompt_staged_rel(voice_id)


def _approved_voice(client, wav_bytes, prompt=b"prompt-A") -> dict:
    voice = _create_voice(client)
    _design_to_preview(client, voice["id"], wav_bytes)
    claim = _approve_and_claim_clone(client, voice["id"])
    _upload(client, claim, "prompt_pt", prompt)
    _complete(client, claim)
    return client.get(f"/api/voices/{voice['id']}").json()


# ---------- 1. missing preview at redesign completion preserves the approval ----------
def test_missing_preview_at_redesign_completion_preserves_approval(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    first_wav = make_wav_bytes(seconds=1.0)
    voice = _approved_voice(client, first_wav, prompt=b"prompt-A")
    saved_ref_path = _voice_row(voice["id"]).reference_audio_path
    saved_prompt_path = _voice_row(voice["id"]).prompt_pt_path

    new_wav = make_wav_bytes(seconds=2.0)
    voice = _design_to_preview(client, voice["id"], new_wav)
    claim = _approve_and_claim_clone(client, voice["id"])
    _upload(client, claim, "prompt_pt", b"prompt-B")

    # The preview disappears before completion (external/manual interference).
    _preview_path(voice["id"]).unlink()
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 422

    # Nothing was mutated: the approved prompt/reference are intact, the staged
    # prompt is untouched, and the voice is still approving.
    row = _voice_row(voice["id"])
    assert row.status == "approving"
    assert row.reference_audio_path == saved_ref_path
    assert storage.safe_resolve(saved_ref_path).read_bytes() == first_wav
    assert row.prompt_pt_path == saved_prompt_path
    assert storage.safe_resolve(saved_prompt_path).read_bytes() == b"prompt-A"
    assert _staged_prompt_path(voice["id"]).is_file()


# ---------- 2. missing preview at first-time completion creates no live slot ----------
def test_missing_preview_at_first_clone_completion_creates_nothing(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _create_voice(client)
    _design_to_preview(client, voice["id"], wav)
    claim = _approve_and_claim_clone(client, voice["id"])
    _upload(client, claim, "prompt_pt", b"prompt-B")

    _preview_path(voice["id"]).unlink()
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 422

    # No reference or prompt was created; the staged prompt survives for retry.
    row = _voice_row(voice["id"])
    assert row.status == "approving"
    assert row.reference_audio_path is None
    assert row.prompt_pt_path is None
    assert not _reference_path(voice["id"]).exists()
    assert not _live_prompt_path(voice["id"]).exists()
    assert _staged_prompt_path(voice["id"]).is_file()


# ---------- 3. exception between promotions preserves the approved prompt ----------
def test_exception_between_promotions_preserves_approved_prompt(
    client, dev_login, make_wav_bytes, monkeypatch
):
    dev_login("alice@example.com")
    first_wav = make_wav_bytes(seconds=1.0)
    voice = _approved_voice(client, first_wav, prompt=b"prompt-A")
    saved_ref_path = _voice_row(voice["id"]).reference_audio_path
    saved_prompt_path = _voice_row(voice["id"]).prompt_pt_path

    new_wav = make_wav_bytes(seconds=2.0)
    voice = _design_to_preview(client, voice["id"], new_wav)
    claim = _approve_and_claim_clone(client, voice["id"])
    _upload(client, claim, "prompt_pt", b"prompt-B")

    # Simulate a crash/exception after the preview was promoted to the live
    # reference but before the staged prompt was promoted. The reference slot is
    # promoted first by design, so this is the point at which a failure must not
    # destroy the previously approved prompt.
    def _boom(voice_id):
        raise RuntimeError("simulated disk failure")

    monkeypatch.setattr(storage, "promote_voice_prompt", _boom)
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 422

    # The reference was promoted (new_wav), but the previously approved prompt
    # survived; the staged prompt was not consumed and the job is still running.
    row = _voice_row(voice["id"])
    assert row.status == "approving"
    assert storage.safe_resolve(saved_ref_path).read_bytes() == new_wav
    assert storage.safe_resolve(saved_prompt_path).read_bytes() == b"prompt-A"
    assert _staged_prompt_path(voice["id"]).is_file()

    # A terminal failure of the retried clone still preserves the approved
    # prompt (the approved reference.wav was superseded by the promotion above).
    _fail_until_terminal(client, claim)
    row = _voice_row(voice["id"])
    assert row.status == "preview_ready"
    assert row.prompt_pt_path == saved_prompt_path
    assert storage.safe_resolve(row.prompt_pt_path).read_bytes() == b"prompt-A"
    assert storage.safe_resolve(row.reference_audio_path).read_bytes() == new_wav
