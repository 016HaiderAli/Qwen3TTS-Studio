"""End-to-end tests for the Built-in Qwen CustomVoice flow.

Covers the full lifecycle:
    POST /api/builtin-voices/generate
        -> validates speaker names and script
        -> creates a Narration (voice_id=NULL) and a queued custom_voice Job
        -> the job is claimed and processed by MockBackend
        -> artifact (chunk_0 WAV) is uploaded and the job is completed
        -> the backend concatenates the chunk(s) into final.wav
        -> the narration transitions to status=ready
        -> the audio file is served via GET /api/files/narrations/{id}/audio
"""
import pytest

from app.custom_voices import list_speakers
from qwen_tts_worker.backends import MockBackend

# Reuse the worker contract helpers from the existing e2e suite.
from test_mock_worker_e2e import (
    WORKER_AUTH,
    _claim_headers,
    _complete,
    _upload,
)

ALL_SPEAKER_IDS = [s.id for s in list_speakers()]
assert len(ALL_SPEAKER_IDS) == 9, "catalog must contain exactly 9 speakers"


def _run_custom_voice_worker(client, mock: MockBackend, max_jobs: int = 5) -> int:
    """Poll and process custom_voice jobs until idle. Returns number processed."""
    processed = 0
    for _ in range(max_jobs):
        resp = client.post("/internal/jobs/poll", headers=WORKER_AUTH)
        if resp.status_code == 204:
            break
        assert resp.status_code == 200
        claim = resp.json()
        assert claim["type"] == "custom_voice"
        processed += 1

        payload = claim["payload"]
        outputs = mock.generate_custom_voice(
            chunks=payload["chunks"],
            speaker=payload["speaker"],
            language=payload["language"],
            instruct=payload["instruct"],
        )
        assert len(outputs) == len(payload["chunks"])
        for i, out in enumerate(outputs):
            _upload(client, claim, f"chunk_{i}", out.wav_bytes)
        _complete(
            client,
            claim,
            outputs[0].sample_rate,
            [o.duration_sec for o in outputs],
        )
    return processed


# ---------------------------------------------------------------------------
# Speaker catalog
# ---------------------------------------------------------------------------

def test_list_builtin_voices_returns_all_9(client):
    """GET /api/builtin-voices returns exactly the 9 official speakers."""
    resp = client.get("/api/builtin-voices")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 9
    ids = {r["id"] for r in data}
    assert ids == set(ALL_SPEAKER_IDS)
    for r in data:
        assert "description" in r
        assert "native_language" in r


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------

def test_generate_unknown_speaker_rejected(client, dev_login):
    """An invalid speaker name returns 400."""
    dev_login("reject@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={
            "speaker": "NotASpeaker",
            "language": "English",
            "script": "Hello world.",
        },
    )
    assert resp.status_code == 400
    assert "Unknown speaker" in resp.json()["detail"]


def test_generate_empty_script_rejected(client, dev_login):
    """An empty or whitespace-only script returns 422."""
    dev_login("empty@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={
            "speaker": "Vivian",
            "language": "English",
            "script": "   ",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Happy-path generation
# ---------------------------------------------------------------------------

def test_generate_custom_voice_single_chunk(client, dev_login):
    """A minimal single-chunk custom_voice job completes and is served as audio."""
    dev_login("cv1@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={
            "speaker": "Vivian",
            "language": "English",
            "script": "Hello, this is a test narration.",
            "title": "Test single chunk",
        },
    )
    assert resp.status_code == 201
    narration = resp.json()
    assert narration["id"]
    assert narration["status"] == "queued"
    assert narration["voice_id"] is None
    assert narration["voice_source"] == "custom_voice"

    # Worker processes the job.
    assert _run_custom_voice_worker(client, MockBackend()) == 1

    # Narration is ready.
    narration = client.get(f"/api/narrations/{narration['id']}").json()
    assert narration["status"] == "ready"
    assert narration["sample_rate"] == 24000
    assert narration["duration_sec"] is not None

    # Audio file is served and is a valid WAV.
    audio = client.get(f"/api/files/narrations/{narration['id']}/audio")
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"


def test_generate_custom_voice_with_instruct(client, dev_login):
    """A custom_voice job with a delivery direction is passed through to the model."""
    dev_login("cv2@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={
            "speaker": "Uncle_Fu",
            "language": "English",
            "script": "Once upon a time in a distant land.",
            "instruct": "Speak slowly and with gravitas, as if reading to a child.",
        },
    )
    assert resp.status_code == 201
    narration = resp.json()

    # Claim the job and verify the instruct field is in the payload.
    resp2 = client.post("/internal/jobs/poll", headers=WORKER_AUTH)
    assert resp2.status_code == 200
    claim = resp2.json()
    assert claim["type"] == "custom_voice"
    assert claim["payload"]["instruct"] == "Speak slowly and with gravitas, as if reading to a child."
    assert claim["payload"]["speaker"] == "Uncle_Fu"

    # Complete it.
    outputs = MockBackend().generate_custom_voice(
        chunks=claim["payload"]["chunks"],
        speaker=claim["payload"]["speaker"],
        language=claim["payload"]["language"],
        instruct=claim["payload"]["instruct"],
    )
    for i, out in enumerate(outputs):
        _upload(client, claim, f"chunk_{i}", out.wav_bytes)
    _complete(client, claim, outputs[0].sample_rate, [o.duration_sec for o in outputs])

    # Narration is ready.
    narration = client.get(f"/api/narrations/{narration['id']}").json()
    assert narration["status"] == "ready"


def test_all_9_speakers_are_accepted(client, dev_login):
    """Every official speaker id is accepted without 400."""
    for i, speaker_id in enumerate(ALL_SPEAKER_IDS):
        email = f"cv{i}@speaker-test.example.com"
        dev_login(email)
        resp = client.post(
            "/api/builtin-voices/generate",
            json={
                "speaker": speaker_id,
                "language": "English",
                "script": f"Testing speaker {speaker_id}.",
            },
        )
        assert resp.status_code == 201, f"speaker {speaker_id!r} was rejected: {resp.json()}"


def test_custom_voice_job_has_correct_type(client, dev_login):
    """The enqueued job has type='custom_voice' and required_backend='mock'."""
    dev_login("cv-type@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={
            "speaker": "Serena",
            "language": "English",
            "script": "Short script.",
        },
    )
    assert resp.status_code == 201

    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["type"] == "custom_voice"
    assert jobs[0]["required_backend"] == "mock"
    assert jobs[0]["status"] == "queued"


def test_custom_voice_appears_in_history(client, dev_login):
    """A completed custom_voice narration shows in the narrations list with voice_source."""
    dev_login("cv-hist@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={
            "speaker": "Dylan",
            "language": "English",
            "script": "This should appear in history.",
            "title": "History test",
        },
    )
    assert resp.status_code == 201
    narration_id = resp.json()["id"]

    _run_custom_voice_worker(client, MockBackend())

    # Check the list endpoint.
    items = client.get("/api/narrations").json()
    found = next((n for n in items if n["id"] == narration_id), None)
    assert found is not None
    assert found["voice_source"] == "custom_voice"
    assert found["voice_id"] is None
    assert found["title"] == "History test"


def test_custom_voice_audio_download(client, dev_login):
    """The audio endpoint supports the ?download=true query param."""
    dev_login("cv-dl@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={
            "speaker": "Aiden",
            "language": "English",
            "script": "Download test.",
        },
    )
    assert resp.status_code == 201
    narration_id = resp.json()["id"]

    _run_custom_voice_worker(client, MockBackend())

    # ?download=true should return Content-Disposition with filename.
    dl_resp = client.get(
        f"/api/files/narrations/{narration_id}/audio?download=true"
    )
    assert dl_resp.status_code == 200
    assert "attachment" in dl_resp.headers.get("Content-Disposition", "")


# ---------------------------------------------------------------------------
# Multi-speaker dialogue narration
# ---------------------------------------------------------------------------


def _run_dialogue_worker(client, mock: MockBackend, max_jobs: int = 5) -> int:
    """Poll and process dialogue custom_voice jobs until idle. Returns number processed."""
    processed = 0
    for _ in range(max_jobs):
        resp = client.post("/internal/jobs/poll", headers=WORKER_AUTH)
        if resp.status_code == 204:
            break
        assert resp.status_code == 200
        claim = resp.json()
        assert claim["type"] == "custom_voice"
        processed += 1

        payload = claim["payload"]
        outputs = mock.generate_custom_voice(
            chunks=payload["chunks"],
            speaker=payload["speaker"],
            language=payload["language"],
            instruct=payload["instruct"],
            dialogue_segments=payload.get("dialogue_segments"),
        )
        seg_count = len(payload.get("dialogue_segments") or payload["chunks"])
        assert len(outputs) == seg_count
        for i, out in enumerate(outputs):
            _upload(client, claim, f"chunk_{i}", out.wav_bytes)
        _complete(
            client,
            claim,
            outputs[0].sample_rate,
            [o.duration_sec for o in outputs],
        )
    return processed


def test_dialogue_segments_two_speakers(client, dev_login):
    """Explicit dialogue_segments with two speakers generates and concatenates correctly."""
    dev_login("dialogue1@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={
            "speaker": "Ryan",
            "language": "English",
            "dialogue_segments": [
                {"speaker": "Ryan", "text": "Hey, are you coming to the party tonight?"},
                {"speaker": "Serena", "text": "I wouldn't miss it for the world!"},
            ],
            "title": "Dialogue test",
        },
    )
    assert resp.status_code == 201
    narration = resp.json()
    assert narration["id"]
    assert narration["status"] == "queued"
    assert narration["chunk_count"] == 2
    assert narration["voice_source"] == "custom_voice"

    # Worker processes both segments.
    assert _run_dialogue_worker(client, MockBackend()) == 1

    # Narration is ready.
    narration = client.get(f"/api/narrations/{narration['id']}").json()
    assert narration["status"] == "ready"
    assert narration["sample_rate"] == 24000

    # Audio file is served and is a valid WAV.
    audio = client.get(f"/api/files/narrations/{narration['id']}/audio")
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"


def test_dialogue_segments_rejects_unknown_speaker(client, dev_login):
    """A dialogue segment naming an unknown speaker returns 400."""
    dev_login("dialogue2@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={
            "speaker": "Ryan",
            "language": "English",
            "dialogue_segments": [
                {"speaker": "Ryan", "text": "Hello."},
                {"speaker": "FakeSpeaker", "text": "Not a real speaker."},
            ],
        },
    )
    assert resp.status_code == 400
    assert "Unknown speaker" in resp.json()["detail"]


def test_dialogue_segments_rejects_empty_text(client, dev_login):
    """A dialogue segment with empty text returns 400."""
    dev_login("dialogue3@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={
            "speaker": "Ryan",
            "language": "English",
            "dialogue_segments": [
                {"speaker": "Ryan", "text": "Hello."},
                {"speaker": "Serena", "text": "   "},
            ],
        },
    )
    assert resp.status_code == 400
    assert "non-empty text" in resp.json()["detail"]


def test_dialogue_auto_detected_from_inline_tags(client, dev_login):
    """Inline [Speaker: ...] tags in the script trigger dialogue mode automatically."""
    dev_login("dialogue4@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={
            "speaker": "Ryan",
            "language": "English",
            "script": "Hello there! [Speaker: Serena] Hi! How are you doing? [Speaker: Ryan] Great, thanks!",
        },
    )
    assert resp.status_code == 201
    narration = resp.json()
    assert narration["status"] == "queued"

    # Job payload should contain dialogue_segments.
    resp2 = client.post("/internal/jobs/poll", headers=WORKER_AUTH)
    assert resp2.status_code == 200
    claim = resp2.json()
    assert "dialogue_segments" in claim["payload"]
    segs = claim["payload"]["dialogue_segments"]
    assert len(segs) == 3

    # Complete the job.
    outputs = MockBackend().generate_custom_voice(
        chunks=claim["payload"]["chunks"],
        speaker=claim["payload"]["speaker"],
        language=claim["payload"]["language"],
        instruct=claim["payload"]["instruct"],
        dialogue_segments=segs,
    )
    for i, out in enumerate(outputs):
        _upload(client, claim, f"chunk_{i}", out.wav_bytes)
    _complete(client, claim, outputs[0].sample_rate, [o.duration_sec for o in outputs])

    narration = client.get(f"/api/narrations/{narration['id']}").json()
    assert narration["status"] == "ready"
    assert narration["chunk_count"] == 3
