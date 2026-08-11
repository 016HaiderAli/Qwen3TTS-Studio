"""Unit tests for stdlib WAV handling and chunk concatenation."""
import io
import wave

import pytest

from app import audio


def _make_wav(sr: int, seconds: float, channels: int = 1, sampwidth: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00" * int(sr * seconds))
    return buf.getvalue()


def test_read_wav_bytes():
    ch, sw, sr, n = audio.read_wav_bytes(_make_wav(24000, 1.0))
    assert (ch, sw, sr, n) == (1, 2, 24000, 24000)


def test_read_wav_bytes_rejects_garbage():
    with pytest.raises(audio.AudioError):
        audio.read_wav_bytes(b"not a wav at all")


def test_validate_wav_bytes_size_limit():
    with pytest.raises(audio.AudioError):
        audio.validate_wav_bytes(_make_wav(24000, 10.0), max_bytes=1000)


def test_concat_wav_files():
    a = _make_wav(22050, 0.5)
    b = _make_wav(22050, 0.25)
    p1 = io.BytesIO(a)
    p2 = io.BytesIO(b)
    p1.name = p2.name = "x.wav"
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        f1 = Path(d) / "a.wav"
        f2 = Path(d) / "b.wav"
        out = Path(d) / "out.wav"
        f1.write_bytes(a)
        f2.write_bytes(b)
        sr, duration = audio.concat_wav_files([f1, f2], out)
        assert out.read_bytes()[:4] == b"RIFF"
    assert sr == 22050
    assert duration == pytest.approx(0.75, abs=0.01)


def test_concat_rejects_sample_rate_mismatch():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        f1 = Path(d) / "a.wav"
        f2 = Path(d) / "b.wav"
        f1.write_bytes(_make_wav(22050, 0.5))
        f2.write_bytes(_make_wav(44100, 0.5))
        with pytest.raises(audio.AudioError, match="sample rate mismatch"):
            audio.concat_wav_files([f1, f2], Path(d) / "out.wav")


def test_concat_empty_raises():
    with pytest.raises(audio.AudioError):
        audio.concat_wav_files([], None)
