"""End-to-end test of the full voice studio flow using the mock GPU worker.

Drives the same internal HTTP contract the real worker uses (poll -> process
with the mock backend -> upload artifacts -> complete), proving the web-tier
workflow: login -> create voice -> design preview -> approve -> narrate -> listen.
"""
import time

from qwen_tts_worker.backends import MockBackend

WORKER_AUTH = {
    "Authorization": "Bearer test-worker-token",
    "X-Worker-Backend": "mock",
}


def _claim_headers(claim):
    return {**WORKER_AUTH, "X-Job-Claim-Token": claim["claim_token"]}


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
            _upload(client, claim, "reference_audio", out.wav_bytes)
            _complete(client, claim, out.sample_rate, [out.duration_sec])
        elif job_type == "clone_prompt":
            pt = mock.create_clone_prompt(
                ref_audio_b64=payload["ref_audio_b64"],
                ref_text=payload["ref_text"],
                language=payload["language"],
            )
            _upload(client, claim, "prompt_pt", pt)
            _complete(client, claim)
        elif job_type == "narration":
            outputs = mock.narrate(
                chunks=payload["chunks"],
                prompt_pt_b64=payload["prompt_pt_b64"],
                language=payload["language"],
                instruct=payload["instruct"],
            )
            for i, out in enumerate(outputs):
                _upload(client, claim, f"chunk_{i}", out.wav_bytes)
            _complete(
                client,
                claim,
                outputs[0].sample_rate,
                [o.duration_sec for o in outputs],
            )
    return processed


def _upload(client, claim, field, data):
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/artifact",
        headers=_claim_headers(claim),
        data={"field": field},
        files={"file": ("a.wav", data, "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text


def _complete(client, claim, sr=None, durations=None):
    body = {}
    if sr is not None:
        body["sample_rate"] = sr
    if durations:
        body["durations"] = durations
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json=body,
    )
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
    _upload(client, claim, "chunk_0", outputs[0].wav_bytes)

    status = client.get(f"/api/jobs/{job_id}").json()
    assert status["job"]["status"] == "running"
    assert status["job"]["progress"] == 50
    assert status["chunk_total"] == 2
    assert status["chunk_done"] == 1

    _upload(client, claim, "chunk_1", outputs[1].wav_bytes)
    _complete(
        client,
        claim,
        outputs[0].sample_rate,
        [o.duration_sec for o in outputs],
    )
    status = client.get(f"/api/jobs/{job_id}").json()
    assert status["job"]["status"] == "succeeded"
    assert status["job"]["progress"] == 100


def test_approval_status_flow(client):
    """approve returns 'approving'; a second approve is rejected; worker completion yields 'approved'."""
    dev = client.get("/auth/dev-login?email=approve-flow@example.com")
    assert dev.status_code == 200
    voice = client.post(
        "/api/voices", json={"name": "A", "language": "English"}
    ).json()
    client.post(
        f"/api/voices/{voice['id']}/design",
        json={"description": "d", "reference_text": "r", "language": "English"},
    )
    assert _run_worker(client, MockBackend()) == 1
    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "preview_ready"

    approv = client.post(f"/api/voices/{voice['id']}/approve")
    assert approv.status_code == 200
    assert approv.json()["status"] == "approving"

    # A second approval while pending is rejected and enqueues no extra job.
    again = client.post(f"/api/voices/{voice['id']}/approve")
    assert again.status_code == 409
    clone_jobs = [
        j
        for j in client.get("/api/jobs").json()
        if j["type"] == "clone_prompt" and j["voice_id"] == voice["id"]
    ]
    assert len(clone_jobs) == 1

    assert _run_worker(client, MockBackend()) == 1
    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "approved"


def test_approval_failure_returns_to_preview_ready(client):
    """A permanently failed clone_prompt job returns the voice to preview_ready so approval can be retried."""
    dev = client.get("/auth/dev-login?email=approve-fail@example.com")
    assert dev.status_code == 200
    voice = client.post(
        "/api/voices", json={"name": "B", "language": "English"}
    ).json()
    client.post(
        f"/api/voices/{voice['id']}/design",
        json={"description": "d", "reference_text": "r", "language": "English"},
    )
    assert _run_worker(client, MockBackend()) == 1
    assert client.post(f"/api/voices/{voice['id']}/approve").status_code == 200

    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "clone_prompt"
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/fail",
        headers=_claim_headers(claim),
        json={"error": "GPU exploded"},
    )
    assert resp.status_code == 200
    claim2 = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim2 is not None
    resp = client.post(
        f"/internal/jobs/{claim2['job_id']}/fail",
        headers=_claim_headers(claim2),
        json={"error": "still broken"},
    )
    assert resp.status_code == 200
    assert client.post("/internal/jobs/poll", headers=WORKER_AUTH).status_code == 204

    voice = client.get(f"/api/voices/{voice['id']}").json()
    assert voice["status"] == "preview_ready"

    # Approval can be retried without regenerating the preview.
    approv = client.post(f"/api/voices/{voice['id']}/approve")
    assert approv.status_code == 200
    assert approv.json()["status"] == "approving"
