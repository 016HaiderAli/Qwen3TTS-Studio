"""Phase 5B tests: silence trimming, LUFS normalization, and format export.

Covers:
- ``app.audio.trim_edge_silence``: -45 dBFS dead-silence trimming with guard
  band, interior pauses untouched, pure silence left intact.
- ``app.audio.normalize_loudness`` / ``postprocess_narration_wav``: BS.1770
  -style -14 LUFS normalization, peak limiting, all-silence no-op.
- ``app.audio.convert_wav_to_format``: WAV passthrough, ffmpeg MP3/FLAC.
- API: ``GET /api/audio/{id}/download?format=...`` auth/validation, WAV
  byte-identity, cached conversions.
- E2E: a completed narration is normalized (post-processing runs at job
  completion) without breaking the existing pause-stitching duration math.
"""
import io
import math
import struct
import wave

import pytest

from app import audio
from qwen_tts_worker.backends import MockBackend

from tests.test_pauses import (
    WORKER_AUTH,
    _approved_voice,
    _claim_headers,
    _complete,
    _run_worker,
    _upload,
)


def _write_wav(path, sr: int, samples: list[int], channels: int = 1) -> None:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    path.write_bytes(buf.getvalue())


def _read_wav(path) -> tuple[int, list[int]]:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    return sr, list(struct.unpack(f"<{len(frames) // 2}h", frames))


def _sine(seconds: float, sr: int = 8000, amp: float = 0.3, freq: float = 440.0) -> list[int]:
    return [int(amp * 32767 * math.sin(2 * math.pi * freq * i / sr)) for i in range(int(sr * seconds))]


def _silence(seconds: float, sr: int = 8000) -> list[int]:
    return [0] * int(sr * seconds)


# ---------- trimming ----------

def test_trim_removes_dead_lead_in_and_out(tmp_path):
    p = tmp_path / "a.wav"
    sr = 8000
    _write_wav(p, sr, _silence(1.0, sr) + _sine(1.0, sr) + _silence(1.0, sr))
    removed = audio.trim_edge_silence(p)
    _, samples = _read_wav(p)
    assert 1.9 <= removed / sr <= 2.0  # guard band keeps ~5 ms per edge
    # Interior signal intact: the sine starts right after the guard band.
    assert max(samples) > 8000
    assert samples[-1] == 0  # faded edge


def test_trim_preserves_interior_silence(tmp_path):
    """An interior pause (Phase 5C stitching) must never be trimmed."""
    p = tmp_path / "b.wav"
    sr = 8000
    _write_wav(p, sr, _sine(0.5, sr) + _silence(1.0, sr) + _sine(0.5, sr))
    removed = audio.trim_edge_silence(p)
    _, samples = _read_wav(p)
    assert removed < sr * 0.06  # only the 5 ms guard bands
    interior_silence = samples[int(sr * 0.5) : int(sr * 1.5)]
    assert all(v == 0 for v in interior_silence)


def test_trim_pure_silence_is_noop(tmp_path):
    p = tmp_path / "c.wav"
    sr = 8000
    original = _silence(2.0, sr)
    _write_wav(p, sr, original)
    removed = audio.trim_edge_silence(p)
    assert removed == 0
    _, samples = _read_wav(p)
    assert len(samples) == len(original)  # untouched


def test_trim_quiet_but_not_silent_audio_is_noop(tmp_path):
    """Audio above the -45 dB threshold must not be touched."""
    p = tmp_path / "d.wav"
    sr = 8000
    samples = _sine(1.0, sr, amp=0.01)  # -40 dBFS: above threshold
    _write_wav(p, sr, samples)
    assert audio.trim_edge_silence(p) == 0


# ---------- loudness normalization ----------

def test_normalize_quiet_tone_to_target(tmp_path):
    p = tmp_path / "n.wav"
    sr = 24000
    _write_wav(p, sr, _sine(2.0, sr, amp=0.02))  # very quiet (-34 dBFS)
    report = audio.normalize_loudness(p, target_lufs=-14.0)
    assert report["applied"] is True
    assert report["gain_db"] > 6.0  # boosted
    assert abs(report["post_lufs"] - (-14.0)) < 1.0  # hits the target


def test_normalize_hot_tone_is_peak_limited_not_clipped(tmp_path):
    p = tmp_path / "h.wav"
    sr = 24000
    # High crest-factor signal: a full-scale 1 ms burst over a quiet bed.
    # Integrated loudness sits near -27 LUFS, so reaching -14 LUFS wants
    # ~+13 dB — which would drive the burst far past full scale. The peak
    # limiter must engage and cap gain at the MAX_PEAK_LINEAR ceiling.
    samples = _sine(2.0, sr, amp=0.01)
    burst_start = sr  # 1 s in
    for i in range(sr // 1000):
        samples[burst_start + i] = int(0.99 * 32767)
    _write_wav(p, sr, samples)
    report = audio.normalize_loudness(p, target_lufs=-14.0)
    _, out_samples = _read_wav(p)
    assert report["limited"] is True
    # The limiter refused any boost: the burst already sits at the ceiling,
    # so the capped gain is exactly 1.0 (file left untouched) instead of the
    # ~+13 dB the loudness target alone would demand.
    assert report["gain_linear"] <= 1.0
    assert max(abs(v) for v in out_samples) <= 32767  # never wraps/clips
    assert max(abs(v) for v in out_samples) / 32768.0 <= audio.MAX_PEAK_LINEAR + 1e-6


def test_normalize_all_silence_is_noop(tmp_path):
    """All-silent audio must stay byte-identical (protects pause-only tails)."""
    p = tmp_path / "s.wav"
    sr = 24000
    original = _silence(1.0, sr)
    _write_wav(p, sr, original)
    report = audio.normalize_loudness(p, target_lufs=-14.0)
    assert report["applied"] is False
    _, samples = _read_wav(p)
    assert samples == original


def test_normalize_stereo_file(tmp_path):
    p = tmp_path / "st.wav"
    sr = 24000
    left = _sine(1.0, sr, amp=0.02)
    stereo = [v for v in left for _ in range(2)]  # interleaved L/R
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{len(stereo)}h", *stereo))
    p.write_bytes(buf.getvalue())
    report = audio.normalize_loudness(p, target_lufs=-14.0)
    assert report["applied"] is True
    with wave.open(str(p), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getnframes() == len(left)


def test_postprocess_reports_duration(tmp_path):
    p = tmp_path / "pp.wav"
    sr = 8000
    _write_wav(p, sr, _silence(0.5, sr) + _sine(1.0, sr) + _silence(0.5, sr))
    report = audio.postprocess_narration_wav(p, target_lufs=-14.0)
    assert report["frames_trimmed"] > 0
    assert 0.9 <= report["duration_sec"] <= 1.02  # guard bands remain


# ---------- format conversion ----------

def test_convert_wav_passthrough(tmp_path):
    src = tmp_path / "src.wav"
    out = tmp_path / "out.wav"
    _write_wav(src, 24000, _sine(0.5, 24000))
    result = audio.convert_wav_to_format(src, out, "wav")
    assert result == out
    assert out.read_bytes() == src.read_bytes()


@pytest.mark.skipif(audio._ffmpeg_bin() is None, reason="ffmpeg not installed")
def test_convert_mp3(tmp_path):
    src = tmp_path / "src.wav"
    _write_wav(src, 24000, _sine(0.5, 24000))
    out = tmp_path / "out.mp3"
    audio.convert_wav_to_format(src, out, "mp3")
    data = out.read_bytes()
    assert data.startswith(b"ID3") or data.startswith(b"\xff\xfb")  # ID3 tag or raw frame


def test_convert_flac_now_unsupported(tmp_path):
    """Phase 6B simplified exports: WAV + MP3 only, FLAC was removed."""
    src = tmp_path / "src.wav"
    _write_wav(src, 8000, [0] * 100)
    with pytest.raises(audio.AudioError, match="unsupported export format"):
        audio.convert_wav_to_format(src, tmp_path / "x.flac", "flac")


def test_convert_rejects_unknown_format(tmp_path):
    src = tmp_path / "src.wav"
    _write_wav(src, 8000, [0] * 100)
    with pytest.raises(audio.AudioError):
        audio.convert_wav_to_format(src, tmp_path / "x.oga", "oga")


# ---------- API: export endpoint ----------

def test_download_endpoint_requires_ready_narration(client):
    client.get("/auth/dev-login?email=export-noaudio@example.com")
    resp = client.get("/api/audio/nonexistent/download")
    assert resp.status_code == 404


def test_download_endpoint_rejects_bad_format(client):
    client.get("/auth/dev-login?email=export-badfmt@example.com")
    resp = client.get("/api/audio/someid/download?format=oga")
    assert resp.status_code == 400
    assert "wav or mp3" in resp.json()["detail"]


def test_download_endpoint_wav_and_conversions(client):
    voice = _approved_voice(client, email="export-full@example.com")
    narration = client.post(
        "/api/narrations",
        json={"voice_id": voice["id"], "script": "Export test. [Pause: 1s] Done.", "language": "English"},
    ).json()
    assert _run_worker(client, MockBackend()) == 1

    # WAV: byte-identical to the stored final artifact.
    wav = client.get(f"/api/audio/{narration['id']}/download?format=wav")
    assert wav.status_code == 200
    assert wav.headers["content-type"] == "audio/wav"
    assert 'attachment; filename="Untitled narration.wav"' in wav.headers["content-disposition"]
    final = client.get(f"/api/files/narrations/{narration['id']}/audio")
    assert wav.content == final.content

    if audio._ffmpeg_bin() is not None:
        # MP3 conversion succeeds and is cached (second fetch identical).
        r1 = client.get(f"/api/audio/{narration['id']}/download?format=mp3")
        assert r1.status_code == 200, r1.text
        assert r1.headers["content-type"].startswith(audio.EXPORT_FORMATS["mp3"]["mime"])
        assert r1.content.startswith(b"ID3") or r1.content.startswith(b"\xff\xfb")
        r2 = client.get(f"/api/audio/{narration['id']}/download?format=mp3")
        assert r2.content == r1.content

    # FLAC was removed in Phase 6B: the endpoint validates formats strictly.
    flac = client.get(f"/api/audio/{narration['id']}/download?format=flac")
    assert flac.status_code == 400
    assert "wav or mp3" in flac.json()["detail"]


def test_download_endpoint_requires_auth(client):
    resp = client.get("/api/audio/whatever/download")
    assert resp.status_code == 401


# ---------- E2E: post-processing runs at completion ----------

def test_e2e_narration_is_postprocessed_and_pauses_preserved(client):
    mock = MockBackend()
    voice = _approved_voice(client, email="postprocess-e2e@example.com")
    narration = client.post(
        "/api/narrations",
        json={
            "voice_id": voice["id"],
            "title": "Post process",
            "script": "Hello there. [Pause: 1s] Welcome back.",
            "language": "English",
        },
    ).json()
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    outputs = mock.narrate(
        chunks=claim["payload"]["chunks"],
        prompt_pt_b64=claim["payload"]["prompt_pt_b64"],
        language=claim["payload"]["language"],
        instruct=claim["payload"]["instruct"],
    )
    for i, out in enumerate(outputs):
        _upload(client, claim, f"chunk_{i}", out.wav_bytes)
    _complete(client, claim, outputs[0].sample_rate, [o.duration_sec for o in outputs])

    done = client.get(f"/api/narrations/{narration['id']}").json()
    assert done["status"] == "ready"
    audio_resp = client.get(f"/api/files/narrations/{narration['id']}/audio")
    assert audio_resp.status_code == 200
    with wave.open(io.BytesIO(audio_resp.content), "rb") as wf:
        sr = wf.getframerate()
        n_frames = wf.getnframes()
    speech_sec = sum(o.duration_sec for o in outputs)
    # The user-stitched 1 s interior pause survives post-processing; duration
    # matches speech + pause within tolerance (loudness gain is time-neutral).
    assert n_frames / sr == pytest.approx(speech_sec + 1.0, abs=0.15)
