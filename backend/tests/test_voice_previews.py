"""Tests for the public built-in voice preview endpoint (Phase 6B polish)."""
import io
import struct
import wave

from app.routers.voice_previews import BUILTIN_PREVIEW_FILES


def _wav_header_size() -> int:
    """RIFF/WAV header is 44 bytes for standard 16-bit PCM."""
    return 44


def test_known_speaker_ids_all_have_files():
    """Every id in BUILTIN_PREVIEW_FILES must point to a real file on disk."""
    from app.routers.voice_previews import PREVIEWS_DIR

    for speaker_id, filename in BUILTIN_PREVIEW_FILES.items():
        path = PREVIEWS_DIR / filename
        assert path.is_file(), f"missing preview asset: {path}"


def test_builtin_preview_returns_inline_wav_with_ranges(client):
    resp = client.get("/api/voices/Serena/preview")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "audio/wav"
    # The literal inline disposition is the IDM-blocker (spec: filename=preview.wav).
    assert resp.headers.get("content-disposition") == 'inline; filename="preview.wav"'
    # FastAPI's FileResponse sets Accept-Ranges so fetch() never 416s.
    assert resp.headers.get("accept-ranges") == "bytes"
    # Valid RIFF header.
    assert resp.content[:4] == b"RIFF"
    assert resp.content[8:12] == b"WAVE"


def test_builtin_preview_404_for_unknown_speaker(client):
    resp = client.get("/api/voices/Nonexistent/preview")
    assert resp.status_code == 404


def test_builtin_preview_accepts_case_and_space_variants(client):
    """The endpoint normalizes ids: lowercase, capitalized, and spaced."""
    for variant in ("uncle_fu", "Uncle_Fu", "UNCLE_FU", "Uncle%20Fu"):
        resp = client.get(f"/api/voices/{variant}/preview")
        assert resp.status_code == 200, f"{variant}: {resp.status_code}"
        # The literal inline header prevents download managers from kicking in.
        assert resp.headers["content-disposition"] == 'inline; filename="preview.wav"'


def test_builtin_preview_cors_allows_frontend_origin(client):
    """DEVLOGIN default frontend origin (Vite :5173) must be CORS-allowed."""
    resp = client.get(
        "/api/voices/Vivian/preview",
        headers={"Origin": "http://localhost:5173"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_builtin_preview_preflight_succeeds(client):
    resp = client.options(
        "/api/voices/serena/preview",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200


def test_builtin_preview_does_not_require_auth(client):
    """Preview endpoint is public so the VoiceSelector works for visitors too."""
    # No dev-login performed — the endpoint must still respond successfully.
    resp = client.get("/api/voices/Vivian/preview")
    assert resp.status_code == 200
    assert resp.content[:4] == b"RIFF"


def test_builtin_preview_decodes_to_valid_wav(client):
    """The served bytes must be a parseable mono/stereo PCM16 WAV."""
    resp = client.get("/api/voices/Dylan/preview")
    assert resp.status_code == 200
    bio = io.BytesIO(resp.content)
    with wave.open(bio, "rb") as wf:
        sr = wf.getframerate()
        assert sr > 0
        frames = wf.readframes(wf.getnframes())
    # At least the WAV header should be present and the frames parse as int16.
    assert len(frames) % 2 == 0
    struct.unpack(f"<{len(frames) // 2}h", frames)  # raises on truncation


def test_all_nine_speaker_previews_stream_200(client):
    """Every shipped built-in speaker preview is reachable, no 404."""
    for speaker_id in BUILTIN_PREVIEW_FILES:
        resp = client.get(f"/api/voices/{speaker_id}/preview")
        assert resp.status_code == 200, f"{speaker_id}: {resp.status_code}"
        assert resp.content[:4] == b"RIFF"


def test_known_speaker_with_missing_file_reports_disk_detail(
    client, monkeypatch, tmp_path
):
    """A known speaker whose file vanished returns the on-disk diagnostic 404."""
    from app.routers import voice_previews

    monkeypatch.setattr(voice_previews, "PREVIEWS_DIR", tmp_path / "previews")
    resp = client.get("/api/voices/vivian/preview")
    assert resp.status_code == 404
    assert "not found on disk" in resp.json()["detail"]
