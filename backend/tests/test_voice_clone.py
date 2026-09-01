"""Phase 7A tests: audio-driven voice cloning from an uploaded reference."""
import io
import math
import struct
import wave

import pytest
from app import storage
from app.db import SessionLocal
from app.models import Job, Voice
from app.routers import voice_clone
from qwen_tts_worker.backends import MockBackend

from tests.test_pauses import _run_worker


@pytest.fixture(autouse=True)
def _clone_static_sandbox(tmp_path, monkeypatch):
    """Sandbox the canonical app-static clone dir so tests leave no repo files."""
    monkeypatch.setattr(voice_clone, "CLONE_STATIC_ROOT", tmp_path / "clone-static")


def make_voice_wav(seconds: float, sr: int = 24000, amp: float = 0.3) -> bytes:
    """Deterministic sine + envelope WAV, shaped like a short spoken clip."""
    n = int(sr * seconds)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            env = min(1.0, (i / sr) / 0.05, (n - i) / sr / 0.05)
            value = amp * env * math.sin(2 * math.pi * 110.0 * i / sr)
            frames += struct.pack("<h", int(value * 32767))
        wf.writeframes(bytes(frames))
    return buf.getvalue()


def _login(client, email: str = "clone@example.com"):
    client.get(f"/auth/dev-login?email={email}")


def _clone(client, wav: bytes, name: str = "My Clone", language: str = "English", fname: str = "sample.wav"):
    return client.post(
        "/api/voices/clone",
        files={"file": (fname, wav, "audio/wav")},
        data={"display_name": name, "language": language},
    )


def test_clone_requires_auth():
    from fastapi.testclient import TestClient
    from app.main import app

    anon = TestClient(app)
    resp = anon.post(
        "/api/voices/clone",
        files={"file": ("s.wav", make_voice_wav(3.0), "audio/wav")},
        data={"display_name": "X"},
    )
    assert resp.status_code in (401, 403)


def test_clone_voice_post_endpoint(client):
    """Contract: POST /api/voices/clone â†’ 200 with id/display_name/reference_url."""
    _login(client)
    resp = _clone(client, make_voice_wav(3.0), name="Contract Clone")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"id", "display_name", "reference_url"}
    assert body["display_name"] == "Contract Clone"
    assert body["reference_url"].startswith(f"/api/files/voices/{body['id']}/reference")


def test_clone_trailing_slash_equivalent(client):
    """Both /api/voices/clone and /api/voices/clone/ resolve identically."""
    _login(client)
    resp = client.post(
        "/api/voices/clone/",
        files={"file": ("sample.wav", make_voice_wav(3.0), "audio/wav")},
        data={"display_name": "Slash Clone", "language": "English"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Slash Clone"


def test_clone_registers_approved_voice_and_files(client):
    _login(client)
    wav = make_voice_wav(3.0)
    resp = _clone(client, wav, name="SenkuClone")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    voice_id = body["id"]
    assert body["display_name"] == "SenkuClone"
    assert body["reference_url"] == f"/api/files/voices/{voice_id}/reference"

    # Canonical spec location: <static>/custom_voices/{id}/reference.wav
    canonical = voice_clone.CLONE_STATIC_ROOT / voice_id / "reference.wav"
    assert canonical.is_file()
    assert canonical.read_bytes()[:4] == b"RIFF"

    # Storage working copy serves through the untouched download endpoint.
    served = client.get(f"/api/files/voices/{voice_id}/reference")
    assert served.status_code == 200
    assert served.content[:4] == b"RIFF"

    # Registered as an approved custom voice.
    voices = client.get("/api/voices").json()
    mine = [v for v in voices if v["id"] == voice_id]
    assert len(mine) == 1
    assert mine[0]["status"] == "approved"
    assert mine[0]["name"] == "SenkuClone"

    # A clone_prompt job is queued so the worker derives the real prompt.
    with SessionLocal() as db:
        job = (
            db.query(Job)
            .filter(Job.voice_id == voice_id, Job.type == "clone_prompt")
            .first()
        )
        assert job is not None and job.status == "queued"
        payload = __import__("json").loads(job.payload_json)
        assert payload["ref_audio_b64"]  # built from the stored reference


@pytest.mark.parametrize(
    ("seconds", "expect_fragment"),
    [
        (1.0, "2 seconds"),  # below the 2 s floor
        (35.0, "30"),        # above the 30 s ceiling
    ],
)
def test_clone_duration_boundaries(client, seconds, expect_fragment):
    _login(client)
    resp = _clone(client, make_voice_wav(seconds))
    assert resp.status_code == 422
    assert expect_fragment in resp.json()["detail"]
    # Nothing registered on rejection.
    assert client.get("/api/voices").json() == []


def test_clone_rejects_unsupported_type(client):
    _login(client)
    resp = _clone(client, b"not audio", fname="notes.txt")
    assert resp.status_code == 422
    assert "WAV" in resp.json()["detail"]


def test_clone_rejects_empty_file(client):
    _login(client)
    resp = _clone(client, b"")
    assert resp.status_code == 422


def test_clone_rejects_unsupported_language(client):
    _login(client)
    resp = _clone(client, make_voice_wav(3.0), language="Klingon")
    assert resp.status_code == 422
    assert "language" in resp.json()["detail"].lower()


def test_clone_reference_is_trimmed_and_normalized(client):
    """The stored reference went through the Phase 5B post-process pipeline."""
    _login(client)
    sr = 24000
    speech = int(0.30 * 32767)
    frames = bytearray()
    for _ in range(sr * 2):  # 2 s of near-silent lead-in (Â±3-amplitude buzz)
        frames += struct.pack("<h", 3 if len(frames) % 4 == 0 else -3)
    for i in range(2 * sr):  # 2 s of loud audio
        v = int(speech * math.sin(2 * math.pi * 300 * i / sr))
        frames += struct.pack("<h", v)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(frames))

    resp = _clone(client, buf.getvalue())
    assert resp.status_code == 200, resp.text  # 4 s total: within 2-30 s
    served = client.get(resp.json()["reference_url"])
    with wave.open(io.BytesIO(served.content), "rb") as wf:
        out_sr, n_frames = wf.getframerate(), wf.getnframes()
    # The dead 2 s lead-in was trimmed: output is ~2 s of audio, not 4 s.
    assert abs(n_frames / out_sr - 2.0) < 0.5
    # Loud audio remains present and healthy (within int16 range, non-silent).
    pcm = struct.unpack(f"<{n_frames}h", served.content[44 : 44 + n_frames * 2])
    assert max(abs(v) for v in pcm) > 2000


def test_cloned_voice_end_to_end_narration_with_mock_worker(client):
    _login(client, email="clone-e2e@example.com")
    mock = MockBackend()
    resp = _clone(client, make_voice_wav(3.0), name="E2E Clone")
    assert resp.status_code == 200
    voice_id = resp.json()["id"]

    assert _run_worker(client, mock) >= 1  # processes the clone_prompt job

    with SessionLocal() as db:
        voice = db.get(Voice, voice_id)
        assert voice.status == "approved"
        assert voice.has_approved_prompt
        assert storage.safe_resolve(voice.prompt_pt_path) is not None

    # The cloned voice narrates through the untouched generation endpoint.
    narration = client.post(
        "/api/narrations",
        json={"voice_id": voice_id, "script": "Cloned voice speaking.", "language": "English"},
    )
    assert narration.status_code == 201, narration.text
    assert _run_worker(client, mock, max_jobs=5) >= 1
    done = client.get(f"/api/narrations/{narration.json()['id']}").json()
    assert done["status"] == "ready"
    audio = client.get(f"/api/files/narrations/{done['id']}/audio")
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"


def test_cloned_voice_zero_shot_narration_without_prompt(client):
    """A clone may narrate before its clone_prompt job completes: the worker
    derives the prompt from the reference audio at generation time."""
    _login(client, email="clone-zero@example.com")
    mock = MockBackend()
    resp = _clone(client, make_voice_wav(3.0), name="Zero Shot")
    assert resp.status_code == 200, resp.text
    voice_id = resp.json()["id"]

    # Simulate a clone whose prompt job never completed (failed terminal), so
    # the only usable artifact is the reference audio.
    from app import jobs as job_service

    with SessionLocal() as db:
        job = db.query(Job).filter(Job.voice_id == voice_id, Job.type == "clone_prompt").one()
        job_service.fail_job(db, job, "worker offline; prompt never derived")
        voice = db.get(Voice, voice_id)
        assert voice.prompt_pt_path is None  # no prompt available
        assert voice.reference_audio_path is not None

    # Narration is allowed despite the missing prompt (reference audio exists).
    narration = client.post(
        "/api/narrations",
        json={"voice_id": voice_id, "script": "Zero-shot clone speaking now.", "language": "English"},
    )
    assert narration.status_code == 201, narration.text
    assert narration.json()["status"] == "queued"

    # The worker consumes the reference audio to build the prompt on the fly.
    assert _run_worker(client, mock, max_jobs=5) >= 1
    done = client.get(f"/api/narrations/{narration.json()['id']}").json()
    assert done["status"] == "ready"
    audio = client.get(f"/api/files/narrations/{done['id']}/audio")
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"


def test_delete_clone_voice_removes_static_copy(client):
    _login(client, email="clone-del@example.com")
    resp = _clone(client, make_voice_wav(3.0), name="ToDelete")
    assert resp.status_code == 200, resp.text
    voice_id = resp.json()["id"]
    canonical = voice_clone.CLONE_STATIC_ROOT / voice_id / "reference.wav"
    assert canonical.is_file()
    # Process the queued clone_prompt job first: deletion of a voice with an
    # active job is guarded by design (409).
    assert _run_worker(client, MockBackend()) >= 1
    assert client.delete(f"/api/voices/{voice_id}").status_code == 204
    assert not canonical.exists()
