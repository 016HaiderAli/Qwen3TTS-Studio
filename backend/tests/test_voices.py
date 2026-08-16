"""Voice management + design workflow API tests."""
import base64

from app import storage
from app.db import SessionLocal
from app.models import Voice

WORKER_AUTH = {
    "Authorization": "Bearer test-worker-token",
    "X-Worker-Backend": "mock",
}


def _create_voice(client, name="My Voice", language="English") -> dict:
    resp = client.post(
        "/api/voices",
        json={"name": name, "language": language, "description": "A calm voice."},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _upload_artifact(client, job_id, field, data):
    resp = client.post(
        f"/internal/jobs/{job_id}/artifact",
        headers=WORKER_AUTH,
        data={"field": field},
        files={"file": ("artifact.bin", data, "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text


def _complete_job(client, job_id):
    resp = client.post(
        f"/internal/jobs/{job_id}/complete",
        headers=WORKER_AUTH,
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 200, resp.text


def _design_until_preview(client, voice_id, wav_bytes) -> dict:
    """Design a voice and run the design job through the internal API."""
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
    _upload_artifact(client, claim["job_id"], "reference_audio", wav_bytes)
    _complete_job(client, claim["job_id"])
    return client.get(f"/api/voices/{voice_id}").json()


def _approve_until_approved(client, voice_id) -> dict:
    """Approve a voice and run the clone job through the internal API."""
    resp = client.post(f"/api/voices/{voice_id}/approve")
    assert resp.status_code == 200, resp.text
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "clone_prompt"
    _upload_artifact(client, claim["job_id"], "prompt_pt", b"mock-prompt")
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=WORKER_AUTH,
        json={},
    )
    assert resp.status_code == 200, resp.text
    return client.get(f"/api/voices/{voice_id}").json()


def _voice_row(voice_id) -> Voice:
    with SessionLocal() as db:
        return db.get(Voice, voice_id)


def test_create_voice_requires_auth(client):
    resp = client.post("/api/voices", json={"name": "X", "language": "English"})
    assert resp.status_code == 401


def test_create_and_list_voices(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    assert voice["status"] == "draft"
    listing = client.get("/api/voices")
    assert listing.status_code == 200
    assert any(v["id"] == voice["id"] for v in listing.json())


def test_unsupported_language_rejected(client, dev_login):
    dev_login("alice@example.com")
    resp = client.post(
        "/api/voices", json={"name": "X", "language": "Klingon"}
    )
    assert resp.status_code == 422


def test_design_enqueues_job(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    resp = client.post(
        f"/api/voices/{voice['id']}/design",
        json={
            "description": "Warm and friendly narrator.",
            "reference_text": "Welcome to our story. Enjoy the journey.",
            "language": "English",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "designing"
    listing = client.get("/api/jobs")
    jobs = [j for j in listing.json() if j["type"] == "design"]
    assert any(j["voice_id"] == voice["id"] for j in jobs)


def test_approve_requires_preview(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    resp = client.post(f"/api/voices/{voice['id']}/approve")
    assert resp.status_code == 409


def test_delete_voice(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    resp = client.delete(f"/api/voices/{voice['id']}")
    assert resp.status_code == 204
    assert client.get("/api/voices").json() == []


def test_voice_isolation_between_users(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)

    # Log in as bob (new TestClient cookie is replaced)
    dev_login("bob@example.com")
    assert client.get(f"/api/voices/{voice['id']}").status_code == 404
    resp = client.post(
        f"/api/voices/{voice['id']}/design",
        json={"description": "x", "reference_text": "y", "language": "English"},
    )
    assert resp.status_code == 404


def test_voice_files_reference_isolated(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    assert client.get(f"/api/files/voices/{voice['id']}/reference").status_code == 404


def test_storage_paths_are_relative():
    assert not storage.voice_reference_rel("abc").startswith("/")
    assert ".." not in storage.narration_chunk_rel("abc", 0)


def test_voice_response_exposes_has_approved_prompt(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    assert voice["has_approved_prompt"] is False


def test_approved_voice_exposes_has_approved_prompt(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design_until_preview(client, voice["id"], make_wav_bytes())
    voice = _approve_until_approved(client, voice["id"])
    assert voice["status"] == "approved"
    assert voice["has_approved_prompt"] is True


def test_design_rejected_while_designing(client, dev_login):
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
    assert resp.json()["status"] == "designing"
    again = client.post(
        f"/api/voices/{voice['id']}/design",
        json={
            "description": "Another.",
            "reference_text": "More text.",
            "language": "English",
        },
    )
    assert again.status_code == 409


def test_design_rejected_while_approving(client, dev_login, make_wav_bytes):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    _design_until_preview(client, voice["id"], make_wav_bytes())
    resp = client.post(f"/api/voices/{voice['id']}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approving"
    again = client.post(
        f"/api/voices/{voice['id']}/design",
        json={
            "description": "Another.",
            "reference_text": "More text.",
            "language": "English",
        },
    )
    assert again.status_code == 409


def test_failed_redesign_of_approved_voice_restores_approved_state(
    client, dev_login, make_wav_bytes
):
    """A redesign that permanently fails returns the approved voice to 'approved'
    and leaves the saved reference/prompt artifacts intact."""
    dev_login("alice@example.com")
    voice = _create_voice(client)
    first_wav = make_wav_bytes(sr=24000, seconds=1.0)
    _design_until_preview(client, voice["id"], first_wav)
    voice = _approve_until_approved(client, voice["id"])
    assert voice["status"] == "approved"
    assert voice["has_approved_prompt"] is True

    saved_ref = _voice_row(voice["id"]).reference_audio_path
    saved_prompt = _voice_row(voice["id"]).prompt_pt_path
    assert saved_ref and saved_prompt
    ref_content = storage.safe_resolve(saved_ref).read_bytes()

    # Redesign: status leaves approved but the saved pair stays intact.
    new_wav = make_wav_bytes(sr=24000, seconds=2.0)
    resp = client.post(
        f"/api/voices/{voice['id']}/design",
        json={
            "description": "New voice.",
            "reference_text": "New reference text.",
            "language": "English",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "designing"
    assert _voice_row(voice["id"]).reference_audio_path == saved_ref
    assert _voice_row(voice["id"]).prompt_pt_path == saved_prompt

    # The redesign artifact lands in the draft preview path, never the approved
    # reference.
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "design"
    _upload_artifact(client, claim["job_id"], "reference_audio", new_wav)
    preview_file = storage.root() / storage.voice_preview_rel(voice["id"])
    assert preview_file.is_file()
    assert preview_file.read_bytes() == new_wav
    assert storage.safe_resolve(saved_ref).read_bytes() == ref_content

    # Fail the redesign until it is terminal (max_job_attempts retries).
    for _ in range(2):
        resp = client.post(
            f"/internal/jobs/{claim['job_id']}/fail",
            headers=WORKER_AUTH,
            json={"error": "GPU exploded"},
        )
        assert resp.status_code == 200, resp.text
        claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH)
        if claim.status_code == 204:
            break
        claim = claim.json()

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "approved"
    assert _voice_row(voice["id"]).reference_audio_path == saved_ref
    assert _voice_row(voice["id"]).prompt_pt_path == saved_prompt
    assert storage.safe_resolve(saved_ref).read_bytes() == ref_content
    assert storage.safe_resolve(saved_prompt).is_file()

    # The approved voice's reference is still streamable.
    audio = client.get(f"/api/files/voices/{voice['id']}/reference")
    assert audio.status_code == 200
    assert audio.content == ref_content


def test_redesign_promotes_new_preview_only_on_new_approval(
    client, dev_login, make_wav_bytes
):
    """A successful redesign keeps the approved pair until the new preview is
    approved, and the new clone prompt is built from exactly that preview."""
    dev_login("alice@example.com")
    voice = _create_voice(client)
    first_wav = make_wav_bytes(sr=24000, seconds=1.0)
    _design_until_preview(client, voice["id"], first_wav)
    voice = _approve_until_approved(client, voice["id"])
    saved_ref = _voice_row(voice["id"]).reference_audio_path
    saved_prompt = _voice_row(voice["id"]).prompt_pt_path

    # Redesign and complete a new preview.
    new_wav = make_wav_bytes(sr=24000, seconds=3.0)
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
    _upload_artifact(client, claim["job_id"], "reference_audio", new_wav)
    _complete_job(client, claim["job_id"])

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "preview_ready"
    # The approved pair is still intact, and the preview serves the new audio.
    assert _voice_row(voice["id"]).reference_audio_path == saved_ref
    assert _voice_row(voice["id"]).prompt_pt_path == saved_prompt
    assert storage.safe_resolve(saved_ref).read_bytes() == first_wav
    audio = client.get(f"/api/files/voices/{voice['id']}/reference")
    assert audio.status_code == 200
    assert audio.content == new_wav

    # Approving builds the clone from exactly the new preview and promotes it.
    resp = client.post(f"/api/voices/{voice['id']}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approving"
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "clone_prompt"
    assert base64.b64decode(claim["payload"]["ref_audio_b64"]) == new_wav
    _upload_artifact(client, claim["job_id"], "prompt_pt", b"prompt-v2")
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=WORKER_AUTH,
        json={},
    )
    assert resp.status_code == 200

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "approved"
    assert voice["has_approved_prompt"] is True
    assert storage.safe_resolve(_voice_row(voice["id"]).reference_audio_path).read_bytes() == new_wav
    assert _voice_row(voice["id"]).prompt_pt_path == storage.voice_prompt_rel(voice["id"])
    assert storage.safe_resolve(_voice_row(voice["id"]).prompt_pt_path).read_bytes() == b"prompt-v2"

    audio = client.get(f"/api/files/voices/{voice['id']}/reference")
    assert audio.content == new_wav
