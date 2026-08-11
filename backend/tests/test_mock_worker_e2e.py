"""End-to-end test of the full voice studio flow using the mock GPU worker.

Drives the same internal HTTP contract the real worker uses (poll -> process
with the mock backend -> upload artifacts -> complete), proving the web-tier
workflow: login -> create voice -> design preview -> approve -> narrate -> listen.
"""
import time

from qwen_tts_worker.backends import MockBackend

WORKER_AUTH = {"Authorization": "Bearer test-worker-token"}


def _run_worker(client, mock: MockBackend, max_jobs: int = 10) -> int:
    """Poll and process jobs until idle. Returns number of jobs processed."""
    processed = 0
    for _ in range(max_jobs):
        resp = client.post("/internal/jobs/poll", headers=WORKER_AUTH)
        if resp.status_code == 204:
            break
        assert resp.status_code == 200
        claim = resp.json()
        processed += 1
        job_id = claim["job_id"]
        job_type = claim["type"]
        payload = claim["payload"]

        if job_type == "design":
            out = mock.design(
                language=payload["language"],
                instruct=payload["instruct"],
                text=payload["text"],
            )
            _upload(client, job_id, "reference_audio", out.wav_bytes)
            _complete(client, job_id, out.sample_rate, [out.duration_sec])
        elif job_type == "clone_prompt":
            pt = mock.create_clone_prompt(
                ref_audio_b64=payload["ref_audio_b64"],
                ref_text=payload["ref_text"],
                language=payload["language"],
            )
            _upload(client, job_id, "prompt_pt", pt)
            _complete(client, job_id)
        elif job_type == "narration":
            outputs = mock.narrate(
                chunks=payload["chunks"],
                prompt_pt_b64=payload["prompt_pt_b64"],
                language=payload["language"],
                instruct=payload["instruct"],
            )
            for i, out in enumerate(outputs):
                _upload(client, job_id, f"chunk_{i}", out.wav_bytes)
            _complete(
                client,
                job_id,
                outputs[0].sample_rate,
                [o.duration_sec for o in outputs],
            )
    return processed


def _upload(client, job_id, field, data):
    resp = client.post(
        f"/internal/jobs/{job_id}/artifact",
        headers=WORKER_AUTH,
        data={"field": field},
        files={"file": ("a.wav", data, "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text


def _complete(client, job_id, sr=None, durations=None):
    body = {}
    if sr is not None:
        body["sample_rate"] = sr
    if durations:
        body["durations"] = durations
    resp = client.post(f"/internal/jobs/{job_id}/complete", headers=WORKER_AUTH, json=body)
    assert resp.status_code == 200, resp.text


def _full_flow(client, script, delivery_direction="", expect_chunks=1):
    dev = client.get("/auth/dev-login?email=e2e@example.com")
    assert dev.status_code == 200

    voice = client.post(
        "/api/voices",
        json={"name": "E2E Voice", "language": "English", "description": "desc"},
    ).json()

    client.post(
        f"/api/voices/{voice['id']}/design",
        json={
            "description": "A warm, friendly narrator.",
            "reference_text": "Welcome to the demo.",
            "language": "English",
        },
    )
    assert _run_worker(client, MockBackend()) >= 1
    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "preview_ready"

    client.post(f"/api/voices/{voice['id']}/approve")
    assert _run_worker(client, MockBackend()) >= 1
    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "approved"

    narration = client.post(
        "/api/narrations",
        json={
            "voice_id": voice["id"],
            "title": "E2E narration",
            "script": script,
            "delivery_direction": delivery_direction,
            "language": "English",
        },
    ).json()
    assert narration["chunk_count"] == expect_chunks

    # progress visible while processing
    job = client.get("/api/jobs").json()[0]
    assert job["status"] == "queued"

    assert _run_worker(client, MockBackend()) >= 1
    narration = client.get(f"/api/narrations/{narration['id']}").json()
    assert narration["status"] == "ready"
    assert narration["chunks_done"] == narration["chunk_count"]
    assert narration["sample_rate"] == 24000
    assert narration["duration_sec"] is not None

    audio = client.get(f"/api/files/narrations/{narration['id']}/audio")
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"

    return narration


def test_full_flow_single_chunk(client):
    _full_flow(client, "Hello world. This is a single chunk.")


def test_full_flow_multi_chunk_with_delivery_direction(client):
    script = " ".join(f"Word number {i} has arrived." for i in range(40))
    narration = _full_flow(
        client,
        script,
        delivery_direction="Speak at a measured, calm pace with brief pauses.",
        expect_chunks=3,
    )
    assert narration["chunk_count"] == 3


def test_full_flow_paragraph_breaks_preserved(client):
    script = "Paragraph one sentence.\n\nParagraph two, different topic.\n\nFinal words here."
    narration = _full_flow(client, script, expect_chunks=1)
    assert narration["chunk_count"] == 1
    job = client.get("/api/jobs").json()[0]
    assert job["status"] == "succeeded"


def test_job_progress_during_narration(client):
    """Chunk-by-chunk upload updates the user-facing job progress."""
    dev = client.get("/auth/dev-login?email=progress@example.com")
    assert dev.status_code == 200
    voice = client.post(
        "/api/voices", json={"name": "V", "language": "English"}
    ).json()
    client.post(
        f"/api/voices/{voice['id']}/design",
        json={"description": "d", "reference_text": "r", "language": "English"},
    )
    assert _run_worker(client, MockBackend()) == 1
    client.post(f"/api/voices/{voice['id']}/approve")
    assert _run_worker(client, MockBackend()) == 1

    script = " ".join(f"Sentence {i}." for i in range(50))
    narration = client.post(
        "/api/narrations",
        json={"voice_id": voice["id"], "script": script},
    ).json()
    assert narration["chunk_count"] == 2

    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    job_id = claim["job_id"]
    outputs = MockBackend().narrate(
        chunks=claim["payload"]["chunks"],
        prompt_pt_b64=claim["payload"]["prompt_pt_b64"],
        language=claim["payload"]["language"],
        instruct=claim["payload"]["instruct"],
    )
    _upload(client, job_id, "chunk_0", outputs[0].wav_bytes)

    status = client.get(f"/api/jobs/{job_id}").json()
    assert status["job"]["status"] == "running"
    assert status["job"]["progress"] == 50
    assert status["chunk_total"] == 2
    assert status["chunk_done"] == 1

    _upload(client, job_id, "chunk_1", outputs[1].wav_bytes)
    _complete(client, job_id, outputs[0].sample_rate, [o.duration_sec for o in outputs])
    status = client.get(f"/api/jobs/{job_id}").json()
    assert status["job"]["status"] == "succeeded"
    assert status["job"]["progress"] == 100
