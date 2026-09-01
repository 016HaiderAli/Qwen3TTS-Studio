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

Phase 5B adds loudness post-processing: dead-silence trimming at the
lead-in/lead-out edges (-45 dBFS threshold) and BS.1770-style integrated
loudness normalization to -14 LUFS (K-weighted, gated, peak-limited) so
finished narrations meet broadcast/podcast loudness without clipping.
MP3/FLAC export conversion shells out to ffmpeg when available.
"""
import math
import os
import shutil
import struct
import subprocess
import tempfile
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


# ---------- Phase 5B: trimming, loudness normalization, export conversion ----------

TRIM_THRESHOLD_DB = -45.0
TARGET_LUFS = -14.0
MAX_PEAK_LINEAR = 0.990  # ~-0.09 dBFS sample-peak ceiling (anti-clipping)


def _read_wav_frames(path: Path) -> tuple[list[bytes], int, int]:
    """Read a PCM16 WAV into per-frame byte strings; return (frames, channels, sample_rate)."""
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        if sampwidth != 2:
            raise AudioError(f"only 16-bit PCM WAV is supported: {path.name}")
        data = wf.readframes(wf.getnframes())
    frame_bytes = 2 * channels
    count = len(data) // frame_bytes
    return [data[i * frame_bytes : (i + 1) * frame_bytes] for i in range(count)], channels, sample_rate


def _write_wav_frames(path: Path, frames: list[bytes], channels: int, sample_rate: int) -> None:
    """Atomically write per-frame byte strings back as a PCM16 WAV."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    write_wav(tmp, sample_rate, b"".join(frames), channels=channels)
    os.replace(tmp, path)


def trim_edge_silence(
    path: Path,
    threshold_db: float = TRIM_THRESHOLD_DB,
    trim_start: bool = True,
    trim_end: bool = True,
) -> int:
    """Trim dead silence from the lead-in and lead-out of a WAV file in place.

    Frames whose every channel sample stays at or below ``threshold_db`` FS
    (default -45 dB) are removed from the start/end of the file; interior
    audio — including intentional Phase 5C pause stitching — is untouched.
    A 5 ms guard band is kept at each cut so speech never starts or ends on
    an abrupt click. A file with no samples above the threshold (pure
    silence) is left byte-identical: trimming a fully silent narration to
    nothing would be destructive.

    Returns the number of frames removed.
    """
    threshold = int(32767 * (10 ** (threshold_db / 20.0)))
    frames, channels, sample_rate = _read_wav_frames(path)
    n = len(frames)

    def _quiet(frame: bytes) -> bool:
        return all(abs(v) <= threshold for v in struct.unpack(f"<{channels}h", frame))

    head = 0
    if trim_start:
        while head < n and _quiet(frames[head]):
            head += 1
    if head >= n:
        # The whole file is below the threshold: leave it byte-identical.
        # Trimming a fully silent narration (e.g. a pause-only stitched tail)
        # to a 5 ms guard band would be destructive, never useful.
        return 0
    tail = 0
    if trim_end:
        while tail < n - head and _quiet(frames[n - 1 - tail]):
            tail += 1

    guard = max(1, int(sample_rate * 0.005))
    head = max(0, head - guard)
    tail = max(0, tail - guard)

    removed = head + tail
    if removed > 0:
        kept = frames[head : n - tail]
        _write_wav_frames(path, kept, channels, sample_rate)
        # Re-fade the fresh edges so the cut never clicks against playback.
        raw, ch, sr = _read_wav_frames(path)
        data = b"".join(raw)
        faded = apply_edge_fades(data, sr, ch, 5.0)
        _write_wav_frames(path, [faded[i : i + 2 * ch] for i in range(0, len(faded), 2 * ch)], ch, sr)
    return removed


def _k_weighted_loudness_lufs(samples: list[int], sample_rate: int) -> float:
    """Integrated loudness (LUFS) of mono PCM16 samples, BS.1770-style.

    Two-stage K-weighting biquad cascade (high-shelf ≈ +4 dB above ~1.7 kHz,
    then a ~38 Hz high-pass) designed at the file's actual sample rate,
    400 ms mean-square windows with 75% overlap (accumulated via 100 ms
    sub-blocks), absolute -70 LUFS gate, then relative gating 10 LU below
    the ungated mean — the same shape ffmpeg ``loudnorm`` implements, in
    pure Python.
    """
    if not samples:
        return -70.0

    sr = sample_rate
    # Stage 1: BS.1770 high-shelf (+3.9998 dB @ 1681.97 Hz, Q 0.7072), RBJ
    # design (matches the hard-coded 48 kHz reference coefficients to <0.05 dB
    # at every rate; DC gain normalizes to exactly 1.0).
    f1, gain1_db, q1 = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    big_a = 10.0 ** (gain1_db / 40.0)
    w1 = 2.0 * math.pi * f1 / sr
    cw1, sw1 = math.cos(w1), math.sin(w1)
    alpha1 = sw1 / (2.0 * q1)
    sq_term = 2.0 * math.sqrt(big_a) * alpha1
    s1a0 = (big_a + 1) - (big_a - 1) * cw1 + sq_term
    b0 = (big_a * ((big_a + 1) + (big_a - 1) * cw1 + sq_term)) / s1a0
    b1 = (-2.0 * big_a * ((big_a - 1) + (big_a + 1) * cw1)) / s1a0
    b2 = (big_a * ((big_a + 1) + (big_a - 1) * cw1 - sq_term)) / s1a0
    a1 = (2.0 * ((big_a - 1) - (big_a + 1) * cw1)) / s1a0
    a2 = ((big_a + 1) - (big_a - 1) * cw1 - sq_term) / s1a0

    # Stage 2: BS.1770 high-pass (38.135 Hz, Q 0.5003), RBJ design
    # (exact match to the 48 kHz reference coefficients).
    f2, q2 = 38.13547087602444, 0.5003270373238773
    w2 = 2.0 * math.pi * f2 / sr
    cw2, sw2 = math.cos(w2), math.sin(w2)
    alpha2 = sw2 / (2.0 * q2)
    s2a0 = 1.0 + alpha2
    c0, c1, c2 = (1.0 + cw2) / 2.0 / s2a0, (-(1.0 + cw2)) / s2a0, (1.0 + cw2) / 2.0 / s2a0
    d1 = (-2.0 * cw2) / s2a0
    d2 = (1.0 - alpha2) / s2a0

    norm = 32768.0
    s1x1 = s1x2 = s1y1 = s1y2 = 0.0
    s2x1 = s2x2 = s2y1 = s2y2 = 0.0
    sub_len = max(1, int(sr * 0.1))  # 100 ms sub-block
    sub_powers: list[float] = []
    acc = 0.0
    acc_n = 0

    for s in samples:
        x = s / norm
        y = b0 * x + b1 * s1x1 + b2 * s1x2 - a1 * s1y1 - a2 * s1y2
        s1x2, s1x1 = s1x1, x
        s1y2, s1y1 = s1y1, y
        z = c0 * y + c1 * s2x1 + c2 * s2x2 - d1 * s2y1 - d2 * s2y2
        s2x2, s2x1 = s2x1, y
        s2y2, s2y1 = s2y1, z

        acc += z * z
        acc_n += 1
        if acc_n == sub_len:
            sub_powers.append(acc / acc_n)
            acc = 0.0
            acc_n = 0

    if acc_n >= sub_len // 2:  # keep a substantial trailing sub-block
        sub_powers.append(acc / acc_n)

    if not sub_powers:
        return -70.0

    def lufs(p: float) -> float:
        return -0.691 + 10.0 * math.log10(p) if p > 0.0 else -70.0

    # 400 ms windows = 4 consecutive 100 ms sub-blocks, 100 ms hop (75% overlap).
    window_len = 4
    window_powers = [
        sum(sub_powers[i : i + window_len]) / min(window_len, len(sub_powers) - i)
        for i in range(len(sub_powers))
        if len(sub_powers) - i >= window_len // 2
    ]
    if not window_powers:
        window_powers = [sum(sub_powers) / len(sub_powers)]

    ungated = [p for p in window_powers if lufs(p) > -70.0]
    if not ungated:
        return max(lufs(sum(window_powers) / len(window_powers)), -70.0)
    rel_threshold = lufs(sum(ungated) / len(ungated)) - 10.0
    # Relative gate excludes blocks BELOW the mean-10 LU floor only; blocks
    # above it (loud bursts) always contribute, as in BS.1770.
    gated = [p for p in ungated if lufs(p) > rel_threshold]
    if not gated:
        return lufs(sum(ungated) / len(ungated))
    return lufs(sum(gated) / len(gated))


def normalize_loudness(
    path: Path,
    target_lufs: float = TARGET_LUFS,
) -> dict:
    """Normalize a WAV file's integrated loudness to ``target_lufs`` in place.

    Applies linear gain to reach the BS.1770-style target, clamped so the
    sample peak never exceeds ``MAX_PEAK_LINEAR`` (prevents clipping on hot
    inputs). All-silent files are left untouched (0 dB gain). Multi-channel
    files are measured via channel-averaged mono, which equals the BS.1770
    equal-weight channel sum for stereo.

    Returns a report: pre/post LUFS, applied gain, peak, and whether the
    peak limiter engaged.
    """
    frames, channels, sample_rate = _read_wav_frames(path)
    data = b"".join(frames)
    samples = list(struct.unpack(f"<{len(data) // 2}h", data))
    if channels == 2:
        mono = [(samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples), 2)]
    else:
        mono = samples

    pre_lufs = _k_weighted_loudness_lufs(mono, sample_rate)
    peak = max((abs(v) for v in samples), default=0) / 32768.0
    if peak == 0.0:
        return {
            "pre_lufs": pre_lufs,
            "post_lufs": pre_lufs,
            "gain_linear": 1.0,
            "gain_db": 0.0,
            "peak_linear": 0.0,
            "limited": False,
            "applied": False,
        }

    gain = 10.0 ** ((target_lufs - pre_lufs) / 20.0)
    limited = False
    if peak * gain > MAX_PEAK_LINEAR:
        gain = MAX_PEAK_LINEAR / peak
        limited = True

    if abs(gain - 1.0) < 1e-4:
        return {
            "pre_lufs": pre_lufs,
            "post_lufs": pre_lufs,
            "gain_linear": 1.0,
            "gain_db": 0.0,
            "peak_linear": peak,
            "limited": limited,
            "applied": False,
        }

    scaled = [max(-32768, min(32767, int(round(v * gain)))) for v in samples]
    out = struct.pack(f"<{len(scaled)}h", *scaled)
    _write_wav_frames(
        path,
        [out[i : i + 2 * channels] for i in range(0, len(out), 2 * channels)],
        channels,
        sample_rate,
    )

    post_samples = list(struct.unpack(f"<{len(scaled)}h", out))
    if channels == 2:
        post_mono = [(post_samples[i] + post_samples[i + 1]) // 2 for i in range(0, len(post_samples), 2)]
    else:
        post_mono = post_samples
    post_peak = max((abs(v) for v in post_samples), default=0) / 32768.0
    return {
        "pre_lufs": round(pre_lufs, 2),
        "post_lufs": round(_k_weighted_loudness_lufs(post_mono, sample_rate), 2),
        "gain_linear": round(gain, 6),
        "gain_db": round(20.0 * math.log10(gain), 2),
        "peak_linear": post_peak,
        "limited": limited,
        "applied": True,
    }


def postprocess_narration_wav(
    path: Path,
    threshold_db: float = TRIM_THRESHOLD_DB,
    target_lufs: float = TARGET_LUFS,
    trim_start: bool = True,
    trim_end: bool = True,
) -> dict:
    """Full Phase 5B pass over a finished narration WAV: trim, then normalize.

    Trimming runs first so lead-in/lead-out silence does not dilute the
    loudness measurement. ``trim_start``/``trim_end`` can be disabled when the
    user explicitly stitched a leading/trailing pause (Phase 5C sequence).
    Returns combined report plus the recomputed duration.
    """
    trimmed = trim_edge_silence(path, threshold_db=threshold_db, trim_start=trim_start, trim_end=trim_end)
    report = normalize_loudness(path, target_lufs=target_lufs)
    report["frames_trimmed"] = trimmed
    _, channels, sample_rate = _read_wav_frames(path)
    with wave.open(str(path), "rb") as wf:
        n = wf.getnframes()
    report["duration_sec"] = round(n / float(sample_rate), 3)
    report["sample_rate"] = sample_rate
    report["channels"] = channels
    return report


# ---------- multi-format export conversion ----------

EXPORT_FORMATS = {
    "wav": {"ext": "wav", "mime": "audio/wav", "args": []},
    "mp3": {"ext": "mp3", "mime": "audio/mpeg", "args": ["-codec:a", "libmp3lame", "-b:a", "192k"]},
}


def _ffmpeg_bin() -> str | None:
    return shutil.which("ffmpeg")


def convert_wav_to_format(source_path: Path, output_path: Path, fmt: str) -> Path | None:
    """Convert a WAV file to ``fmt`` (wav/mp3) via ffmpeg.

    ``wav`` copies the source unchanged (no re-encode, no quality loss).
    MP3 uses libmp3lame at 192 kbps. Returns the output path, or ``None``
    when ffmpeg is unavailable on the server — callers degrade to serving
    the original WAV with a warning.

    Raises:
        AudioError: on unsupported formats or ffmpeg failure.
    """
    fmt = fmt.lower()
    if fmt not in EXPORT_FORMATS:
        raise AudioError(f"unsupported export format: {fmt!r}")
    if fmt == "wav":
        shutil.copyfile(source_path, output_path)
        return output_path

    ffmpeg = _ffmpeg_bin()
    if ffmpeg is None:
        return None

    spec = EXPORT_FORMATS[fmt]
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(source_path),
        *spec["args"],
        str(output_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=120,
            creationflags=getattr(os, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioError(f"ffmpeg {fmt} conversion timed out") from exc
    if result.returncode != 0 or not output_path.is_file():
        stderr = result.stderr.decode(errors="replace")[:400]
        raise AudioError(f"ffmpeg {fmt} conversion failed: {stderr}")
    return output_path
