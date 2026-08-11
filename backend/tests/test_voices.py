"""Voice management + design workflow API tests."""
from app import storage
from app.db import SessionLocal
from app.models import Voice


def _create_voice(client, name="My Voice", language="English") -> dict:
    resp = client.post(
        "/api/voices",
        json={"name": name, "language": language, "description": "A calm voice."},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


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
