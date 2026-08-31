"""WAV reading/writing and chunk concatenation (CPU only, stdlib).

Ports the proven concatenation behavior of reference/Voice_Studio.ipynb
cell 50: verify a consistent sample rate across chunks, concatenate frames,
and write a single final WAV. Uses only the stdlib ``wave``/``struct`` modules
so the web tier does not depend on numpy/soundfile/PyTorch.

Phase 5C adds pause-aware stitching: zero-filled PCM16 silence buffers (the
stdlib byte-identical equivalent of ``np.zeros(int(sr * sec), np.int16)``) are
concatenated between speech chunks in exact sequence order, and every speech
chunk gets an ultra-short linear fade-in/out at its edges so butt-joined
speech/silence boundaries never click or pop.
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


def make_silence_buffer(sample_rate: int, duration_sec: float, channels: int = 1) -> bytes:
    """Return a zero-filled PCM16 silence buffer for the given duration.

    The byte-identical stdlib equivalent of
    ``np.zeros(int(sample_rate * duration_sec), dtype=np.int16)`` (stereo
    interleaves the same zeros per channel).
    """
    n_samples = int(sample_rate * duration_sec)
    if n_samples <= 0:
        return b""
    return b"\x00\x00" * (n_samples * channels)


def apply_edge_fades(
    pcm16_frames: bytes,
    sample_rate: int,
    channels: int = 1,
    fade_ms: float = 5.0,
) -> bytes:
    """Apply an ultra-short linear fade-in/out to PCM16 frames.

    Prevents the digital clicks/pops (DC-offset steps) that occur when a
    non-zero speech tail is butt-joined against zero-filled silence. The fade
    length defaults to 5 ms — short enough to be inaudible, long enough to
    ramp the sample discontinuity to zero. Frames at the very edges already
    at/near zero are unaffected (multiplying by a ramp ≤ 1 preserves them).
    """
    if fade_ms <= 0 or not pcm16_frames:
        return pcm16_frames
    bytes_per_frame = 2 * channels
    n_frames = len(pcm16_frames) // bytes_per_frame
    if n_frames == 0:
        return pcm16_frames
    fade_frames = min(n_frames, max(1, int(sample_rate * fade_ms / 1000)))
    samples = list(
        struct.unpack(f"<{n_frames * channels}h", pcm16_frames[: n_frames * bytes_per_frame])
    )
    for i in range(fade_frames):
        ramp = i / fade_frames
        for c in range(channels):
            samples[i * channels + c] = int(samples[i * channels + c] * ramp)
        tail = n_frames - 1 - i
        samples[tail * channels + c] = int(samples[tail * channels + c] * ramp)
    return struct.pack(f"<{n_frames * channels}h", *samples)


def concat_wav_sequence(
    wav_paths: list[Path],
    sequence: list[dict],
    output_path: Path,
    fade_ms: float = 5.0,
) -> tuple[int, float]:
    """Concatenate speech chunks and silence buffers in exact sequence order.

    ``sequence`` items alternate between ``{"type": "speech",
    "chunk_index": N}`` (the Nth WAV from ``wav_paths``) and
    ``{"type": "pause", "duration_sec": S}`` (a zero-filled PCM16 silence
    buffer of S seconds at the chunks' sample rate). Each speech chunk is
    edge-faded (see :func:`apply_edge_fades`) before merging so speech→silence
    and silence→speech boundaries are click-free.

    Verifies channels/sample-rate consistency like :func:`concat_wav_files`.
    Returns (sample_rate, duration_seconds).
    """
    if not sequence:
        raise AudioError("empty audio sequence")
    if not wav_paths:
        raise AudioError("no speech chunks to concatenate")

    frames = b""
    channels = None
    sampwidth = None
    sample_rate = None
    # Leading pauses precede the first speech chunk, whose WAV metadata defines
    # the sample rate the silence must use — defer them until it is known.
    pending_silence = 0.0
    saw_speech = False

    def _chunk_frames(index: int) -> bytes:
        if index < 0 or index >= len(wav_paths):
            raise AudioError(f"chunk index {index} out of range")
        chunk_frames, ch, sw, sr = _read_wav_file(wav_paths[index])
        nonlocal channels, sampwidth, sample_rate
        if channels is None:
            channels, sampwidth, sample_rate = ch, sw, sr
        elif (ch, sw, sr) != (channels, sampwidth, sample_rate):
            raise AudioError(
                f"sample rate mismatch: {wav_paths[index].name} uses {sr} Hz, expected {sample_rate} Hz"
            )
        return chunk_frames

    for item in sequence:
        kind = item.get("type")
        if kind == "speech":
            raw = _chunk_frames(int(item["chunk_index"]))
            saw_speech = True
            if pending_silence > 0:
                frames += make_silence_buffer(int(sample_rate), pending_silence, int(channels))
                pending_silence = 0.0
            frames += apply_edge_fades(raw, int(sample_rate), int(channels), fade_ms)
        elif kind == "pause":
            duration = float(item.get("duration_sec", 0.0))
            if duration < 0:
                raise AudioError("pause duration must be non-negative")
            if sample_rate is None:
                pending_silence += duration
            elif duration > 0:
                frames += make_silence_buffer(int(sample_rate), duration, int(channels))
        else:
            raise AudioError(f"unknown sequence item type: {kind!r}")

    if not saw_speech:
        raise AudioError("no speech chunks to concatenate")
    if pending_silence > 0:
        frames += make_silence_buffer(int(sample_rate), pending_silence, int(channels))

    if sampwidth != 2:
        raise AudioError("only 16-bit PCM WAV chunks are supported for concatenation")

    write_wav(output_path, int(sample_rate), frames, channels=int(channels))
    frame_count = len(frames) // (sampwidth * channels)
    duration = frame_count / float(sample_rate)
    return int(sample_rate), round(duration, 3)
