"""WAV reading/writing and chunk concatenation (CPU only, stdlib).

Ports the proven concatenation behavior of reference/Voice_Studio.ipynb
cell 50: verify a consistent sample rate across chunks, concatenate frames,
and write a single final WAV. Uses only the stdlib ``wave``/``struct`` modules
so the web tier does not depend on numpy/soundfile/PyTorch.
"""
import struct
import wave
from pathlib import Path


class AudioError(Exception):
    pass


def read_wav_bytes(data: bytes) -> tuple[int, int, int, int]:
    """Return (channels, sample_width, frame_rate, frame_count) for WAV bytes."""
    import io

    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            return wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()
    except (wave.Error, struct.error, EOFError, OSError) as exc:
        raise AudioError(f"invalid WAV data: {exc}") from exc


def _read_wav_file(path: Path) -> tuple[bytes, int, int, int]:
    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
            return frames, channels, sampwidth, framerate
    except (wave.Error, EOFError, OSError) as exc:
        raise AudioError(f"cannot read {path.name}: {exc}") from exc


def validate_wav_bytes(data: bytes, max_bytes: int) -> tuple[int, int, int, int]:
    """Validate WAV bytes and enforce a size limit. Returns WAV metadata."""
    if len(data) > max_bytes:
        raise AudioError("audio exceeds the allowed size limit")
    return read_wav_bytes(data)


def write_wav(path: Path, sample_rate: int, pcm16_frames: bytes, channels: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16_frames)


def concat_wav_files(
    input_paths: list[Path],
    output_path: Path,
    silence_ms: int = 0,
) -> tuple[int, float]:
    """Concatenate WAV files in order.

    Verifies channels/sample-rate consistency (cell 50 behavior) and writes a
    single PCM16 WAV. Returns (sample_rate, duration_seconds).

    Args:
        input_paths: Ordered list of WAV file paths to concatenate.
        output_path: Destination path for the combined WAV.
        silence_ms: Milliseconds of silence to insert between consecutive files.
            Defaults to 0 (no gap). Must be non-negative.
    """
    if not input_paths:
        raise AudioError("no chunks to concatenate")
    if silence_ms < 0:
        raise AudioError("silence_ms must be non-negative")

    frames = b""
    channels = None
    sampwidth = None
    sample_rate = None

    for idx, path in enumerate(input_paths):
        chunk_frames, ch, sw, sr = _read_wav_file(path)
        if channels is None:
            channels, sampwidth, sample_rate = ch, sw, sr
        elif (ch, sw, sr) != (channels, sampwidth, sample_rate):
            raise AudioError(
                f"sample rate mismatch: {path.name} uses {sr} Hz, expected {sample_rate} Hz"
            )
        frames += chunk_frames

        # Insert silence gap between chunks (but not after the last one).
        if silence_ms > 0 and idx < len(input_paths) - 1:
            silence_frames = _make_silence(int(sample_rate), channels, silence_ms)
            frames += silence_frames

    if sampwidth != 2:
        raise AudioError("only 16-bit PCM WAV chunks are supported for concatenation")

    write_wav(output_path, int(sample_rate), frames, channels=int(channels))
    frame_count = len(frames) // (sampwidth * channels)
    duration = frame_count / float(sample_rate)
    return int(sample_rate), round(duration, 3)


def _make_silence(sample_rate: int, channels: int, duration_ms: int) -> bytes:
    """Return PCM16 silence frames for the given duration."""
    n_samples = int(sample_rate * duration_ms / 1000)
    return b"\x00\x00" * (n_samples * channels)
