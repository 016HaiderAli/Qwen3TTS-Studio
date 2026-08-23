"""Regression tests for Phase 2 #4: ``complete_job`` validates before succeeding.

The owning voice/narration is validated (and, for narration jobs, every expected
chunk file) BEFORE the job is transitioned to ``succeeded``, so a completion
whose parent disappeared cannot leave a ``succeeded`` job with a dangling
reference.

The parent rows are deleted on a raw SQLite connection with foreign-key
enforcement temporarily disabled: with enforcement on, the ``ondelete=CASCADE``
constraints would cascade the dependent job rows away, which is exactly why the
dangling-parent state is unreachable through normal SQL. Disabling it here
simulates the only realistic way a parent can vanish while its job still exists
(a bypass of the deletion guards, or manual DB edits) and locks in the
validate-before-success ordering.
"""
import sqlite3

from sqlalchemy import text

from app.config import get_settings
from app.db import engine

WORKER_AUTH = {
    "Authorization": "Bearer test-worker-token",
    "X-Worker-Backend": "mock",
}


def _claim_headers(claim):
    return {**WORKER_AUTH, "X-Job-Claim-Token": claim["claim_token"]}


def _create_voice(client):
    resp = client.post(
        "/api/voices",
        json={"name": "My Voice", "language": "English", "description": "A calm voice."},
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


def _design_to_running(client, voice_id) -> dict:
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
    return claim


def _approved_voice(client, wav) -> dict:
    voice = _create_voice(client)
    claim = _design_to_running(client, voice["id"])
    _upload(client, claim, "reference_audio", wav)
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(f"/api/voices/{voice['id']}/approve")
    assert resp.status_code == 200, resp.text
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "clone_prompt"
    _upload(client, claim, "prompt_pt", b"mock-prompt")
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={},
    )
    assert resp.status_code == 200, resp.text
    return client.get(f"/api/voices/{voice['id']}").json()


def _delete_row_fk_off(table: str, row_id: str) -> None:
    """Delete a row on a raw connection with foreign-key enforcement disabled."""
    url = get_settings().database_url
    path = url.replace("sqlite:///", "", 1)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        conn.commit()
    finally:
        conn.close()


def _job_status(job_id: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id}
        ).scalar()


def _count_succeeded_dangling(column: str, parent_table: str) -> int:
    """Count succeeded jobs whose parent column points at a missing row."""
    sql = (
        f"SELECT COUNT(*) FROM jobs j "
        f"LEFT JOIN {parent_table} p ON j.{column} = p.id "
        f"WHERE j.status = 'succeeded' AND j.{column} IS NOT NULL AND p.id IS NULL"
    )
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar()


def _voice_prompt_path(voice_id: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT prompt_pt_path FROM voices WHERE id = :id"),
            {"id": voice_id},
        ).scalar()


def test_complete_with_missing_voice_does_not_succeed(client, dev_login):
    dev_login("alice@example.com")
    voice = _create_voice(client)
    claim = _design_to_running(client, voice["id"])

    _delete_row_fk_off("voices", voice["id"])

    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 422
    assert _job_status(claim["job_id"]) != "succeeded"
    assert _count_succeeded_dangling("voice_id", "voices") == 0


def test_complete_with_missing_narration_does_not_succeed(
    client, dev_login, make_wav_bytes
):
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _approved_voice(client, wav)

    resp = client.post(
        "/api/narrations", json={"voice_id": voice["id"], "script": "Hello there."}
    )
    assert resp.status_code == 201, resp.text
    narration = resp.json()
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "narration"
    for i in range(len(claim["payload"]["chunks"])):
        _upload(client, claim, f"chunk_{i}", wav)

    _delete_row_fk_off("narrations", narration["id"])

    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 422
    assert _job_status(claim["job_id"]) != "succeeded"
    assert _count_succeeded_dangling("narration_id", "narrations") == 0


def test_complete_design_without_artifact_does_not_succeed(client, dev_login):
    """A design completion without the required preview artifact is rejected."""
    dev_login("alice@example.com")
    voice = _create_voice(client)
    claim = _design_to_running(client, voice["id"])

    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 422
    assert _job_status(claim["job_id"]) != "succeeded"
    assert client.get(f"/api/voices/{voice['id']}").json()["status"] != "preview_ready"


def test_complete_clone_prompt_without_artifact_does_not_succeed(
    client, dev_login, make_wav_bytes
):
    """A clone-prompt completion without the required .pt artifact is rejected."""
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _create_voice(client)
    claim = _design_to_running(client, voice["id"])
    _upload(client, claim, "reference_audio", wav)
    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0]},
    )
    assert resp.status_code == 200, resp.text

    resp = client.post(f"/api/voices/{voice['id']}/approve")
    assert resp.status_code == 200, resp.text
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "clone_prompt"

    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={},
    )
    assert resp.status_code == 422
    assert _job_status(claim["job_id"]) != "succeeded"
    assert client.get(f"/api/voices/{voice['id']}").json()["status"] != "approved"
    assert _voice_prompt_path(voice["id"]) is None


def test_complete_narration_with_missing_chunk_does_not_succeed(
    client, dev_login, make_wav_bytes
):
    """A narration completion with an expected chunk file missing is rejected."""
    dev_login("alice@example.com")
    wav = make_wav_bytes()
    voice = _approved_voice(client, wav)

    script = " ".join(f"Sentence {i}." for i in range(50))
    resp = client.post(
        "/api/narrations", json={"voice_id": voice["id"], "script": script}
    )
    assert resp.status_code == 201, resp.text
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "narration"
    count = len(claim["payload"]["chunks"])
    assert count >= 2
    for i in range(count - 1):
        _upload(client, claim, f"chunk_{i}", wav)

    resp = client.post(
        f"/internal/jobs/{claim['job_id']}/complete",
        headers=_claim_headers(claim),
        json={"sample_rate": 24000, "durations": [1.0] * count},
    )
    assert resp.status_code == 422
    assert _job_status(claim["job_id"]) != "succeeded"
