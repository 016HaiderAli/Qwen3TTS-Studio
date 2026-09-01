"""Phase 5C tests: pause-tag parsing, silence stitching, and click prevention.

Covers:
- ``app/pauses``: regex parsing (s/ms, case-insensitive, whitespace tolerance),
  duration conversion, tag stripping, and script splitting into ordered
  speech/pause sequences.
- ``app/chunking.chunk_script_with_pauses``: pause-aware chunking with exact
  sequence order and unchanged no-pause behavior.
- ``app/audio``: zero-filled PCM16 silence buffers, ultra-short edge fades
  (click/pop prevention), and sequence-aware concatenation.
- API level: narration + built-in voice jobs carry the pause sequence, tags
  are stripped from worker text, and the final WAV duration includes silence.
"""
import io
import struct
import wave

import pytest

from app import audio, chunking, pauses
from qwen_tts_worker.backends import MockBackend

WORKER_AUTH = {
    "Authorization": "Bearer test-worker-token",
    "X-Worker-Backend": "mock",
}


def _claim_headers(claim):
    return {**WORKER_AUTH, "X-Job-Claim-Token": claim["claim_token"]}


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


def _run_worker(client, mock: MockBackend, max_jobs: int = 10) -> int:
    """Poll and process every pending job with the mock backend."""
    processed = 0
    for _ in range(max_jobs):
        resp = client.post("/internal/jobs/poll", headers=WORKER_AUTH)
        if resp.status_code == 204:
            break
        assert resp.status_code == 200
        claim = resp.json()
        processed += 1
        payload = claim["payload"]
        if claim["type"] == "design":
            out = mock.design(
                language=payload["language"],
                instruct=payload["instruct"],
                text=payload["text"],
            )
            _upload(client, claim, "reference_audio", out.wav_bytes)
            _complete(client, claim, out.sample_rate, [out.duration_sec])
        elif claim["type"] == "clone_prompt":
            pt = mock.create_clone_prompt(
                ref_audio_b64=payload["ref_audio_b64"],
                ref_text=payload["ref_text"],
                language=payload["language"],
            )
            _upload(client, claim, "prompt_pt", pt)
            _complete(client, claim)
        elif claim["type"] == "narration":
            # Mirror the real worker logic: if the payload has no clone prompt,
            # derive one from the reference audio (Phase 7A zero-shot path).
            prompt_pt_b64 = payload.get("prompt_pt_b64")
            if not prompt_pt_b64:
                # Zero-shot: ref_text may legitimately be empty (it is optional
                # embedding guidance and must never be a placeholder).
                ref_audio_b64 = payload.get("ref_audio_b64") or ""
                ref_text = payload.get("ref_text") or ""
                language = payload.get("language") or "English"
                pt_bytes = mock.create_clone_prompt(
                    ref_audio_b64=ref_audio_b64, ref_text=ref_text, language=language,
                )
                import base64

                prompt_pt_b64 = base64.b64encode(pt_bytes).decode("ascii")
            outputs = mock.narrate(
                chunks=payload["chunks"],
                prompt_pt_b64=prompt_pt_b64,
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
        elif claim["type"] == "custom_voice":
            outputs = mock.generate_custom_voice(
                chunks=payload["chunks"],
                speaker=payload["speaker"],
                language=payload["language"],
                instruct=payload["instruct"],
                dialogue_segments=payload.get("dialogue_segments"),
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


def _approved_voice(client, email: str = "pauses@example.com") -> dict:
    """Create, design, and approve a cloned voice; returns the voice dict."""
    client.get(f"/auth/dev-login?email={email}")
    voice = client.post("/api/voices", json={"name": "V", "language": "English"}).json()
    client.post(
        f"/api/voices/{voice['id']}/design",
        json={"description": "d", "reference_text": "r", "language": "English"},
    )
    _run_worker(client, MockBackend())
    client.post(f"/api/voices/{voice['id']}/approve")
    _run_worker(client, MockBackend())
    return voice


# ---------- pauses: parsing ----------

@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("[Pause: 1.5s]", 1.5),
        ("[Pause: 500ms]", 0.5),
        ("[Pause: 2s]", 2.0),
        ("[pause: 2S]", 2.0),
        ("[PAUSE: 0.25s]", 0.25),
        ("[Pause:  1s  ]", 1.0),
        ("[Pause: 0.05s]", 0.05),
    ],
)
def test_extract_pause_seconds_valid(tag, expected):
    assert pauses.extract_pause_seconds(tag) == pytest.approx(expected)


@pytest.mark.parametrize(
    "tag",
    ["[Pause: 1]", "[Pause: s]", "[Pause 1s]", "[pause: -1s]", "Pause: 1s", "[Pause: 1.5.5s]"],
)
def test_extract_pause_seconds_invalid(tag):
    assert pauses.extract_pause_seconds(tag) is None


def test_parse_pause_seconds_clamps_extreme_values():
    assert pauses.parse_pause_seconds("999999", "s") == pauses.MAX_PAUSE_SECONDS
    assert pauses.parse_pause_seconds("999999999", "ms") == pauses.MAX_PAUSE_SECONDS


def test_strip_pause_tags():
    assert pauses.strip_pause_tags("Hello [Pause: 1s] world") == "Hello world"
    assert pauses.strip_pause_tags("A. [Pause: 500ms]  B.") == "A. B."
    assert pauses.strip_pause_tags("no tags here") == "no tags here"


def test_has_pause_tags():
    assert pauses.has_pause_tags("text [Pause: 1s] more")
    assert not pauses.has_pause_tags("plain text")


def test_split_on_pauses_without_tags_returns_single_speech():
    items = pauses.split_on_pauses("Hello world.")
    assert len(items) == 1
    assert items[0].kind == "speech"
    assert items[0].text == "Hello world."


def test_split_on_pauses_middle_tag():
    items = pauses.split_on_pauses("Before [Pause: 1s] After")
    assert [(i.kind, i.text if i.kind == "speech" else i.duration_sec) for i in items] == [
        ("speech", "Before"),
        ("pause", 1.0),
        ("speech", "After"),
    ]


def test_split_on_pauses_leading_and_trailing_tags():
    items = pauses.split_on_pauses("[Pause: 0.5s] Start [Pause: 2s]")
    assert [i.kind for i in items] == ["pause", "speech", "pause"]
    assert items[0].duration_sec == pytest.approx(0.5)
    assert items[1].text == "Start"
    assert items[2].duration_sec == pytest.approx(2.0)


def test_split_on_pauses_consecutive_tags_no_empty_speech():
    items = pauses.split_on_pauses("A [Pause: 1s] [Pause: 500ms] B")
    assert [i.kind for i in items] == ["speech", "pause", "pause", "speech"]
    assert all(i.text for i in items if i.kind == "speech")


def test_pause_tag_after_speaker_tag_not_swallowed_as_instruct():
    """The dialogue instruct capture must not swallow pause tags."""
    from app.dialogue import parse_dialogue_script

    segments = parse_dialogue_script(
        "[Speaker: Ryan] [Pause: 1s] Hello", default_speaker="Vivian"
    )
    assert len(segments) == 1
    assert segments[0].speaker == "Ryan"
    assert segments[0].segment_instruct == ""
    # The pause tag survives in the text for the Phase 5C splitter.
    assert "[Pause: 1s]" in segments[0].text
    items = pauses.split_on_pauses(segments[0].text)
    assert [i.kind for i in items] == ["pause", "speech"]
    assert items[1].text == "Hello"


# ---------- chunking: pause-aware chunking ----------

def test_chunk_script_with_pauses_no_tags_matches_chunk_script():
    text = " ".join(f"word{i}." for i in range(100))
    chunks, sequence = chunking.chunk_script_with_pauses(text, max_words_per_chunk=80)
    assert chunks == chunking.chunk_script(text, max_words_per_chunk=80)
    assert sequence is None


def test_chunk_script_with_pauses_sequence_order():
    text = "First part here. [Pause: 1.5s] Second part."
    chunks, sequence = chunking.chunk_script_with_pauses(text)
    assert chunks == ["First part here.", "Second part."]
    assert sequence == [
        {"type": "speech", "chunk_index": 0},
        {"type": "pause", "duration_sec": 1.5},
        {"type": "speech", "chunk_index": 1},
    ]


def test_chunk_script_with_pauses_piece_packing_renumbers_indices():
    piece = " ".join(f"word{i}." for i in range(100))  # packs into 2 chunks
    text = f"{piece} [Pause: 1s] Short tail."
    chunks, sequence = chunking.chunk_script_with_pauses(text, max_words_per_chunk=80)
    assert len(chunks) == 3
    assert chunks[2] == "Short tail."
    assert sequence == [
        {"type": "speech", "chunk_index": 0},
        {"type": "speech", "chunk_index": 1},
        {"type": "pause", "duration_sec": 1.0},
        {"type": "speech", "chunk_index": 2},
    ]


def test_chunk_script_with_pauses_pause_only_script_raises():
    with pytest.raises(ValueError):
        chunking.chunk_script_with_pauses("[Pause: 1s] [Pause: 500ms]")


def test_chunk_script_with_pauses_leading_and_trailing():
    chunks, sequence = chunking.chunk_script_with_pauses("[Pause: 0.5s] Talk. [Pause: 1s]")
    assert chunks == ["Talk."]
    assert sequence == [
        {"type": "pause", "duration_sec": 0.5},
        {"type": "speech", "chunk_index": 0},
        {"type": "pause", "duration_sec": 1.0},
    ]


# ---------- audio: silence buffers, fades, sequence concat ----------

def _write_wav(path, sr: int, samples: list[int], channels: int = 1) -> None:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    path.write_bytes(buf.getvalue())


def _read_samples(path) -> tuple[int, list[int]]:
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    return sr, list(struct.unpack(f"<{len(frames) // 2}h", frames))


def test_make_silence_buffer_length_and_content():
    buf = audio.make_silence_buffer(24000, 1.5)
    assert len(buf) == int(24000 * 1.5) * 2  # int16 mono
    assert buf == b"\x00" * len(buf)
    assert audio.make_silence_buffer(24000, 0.0) == b""


def test_apply_edge_fades_ramps_edges_to_zero():
    sr = 1000  # 5 ms fade == 5 frames
    samples = [1000] * 100
    out = struct.unpack(
        "<100h", audio.apply_edge_fades(struct.pack("<100h", *samples), sr, 1, 5.0)
    )
    assert out[0] == 0  # fades in from zero
    assert out[4] < 1000  # still ramping inside the fade window
    assert out[4] < out[5] == 1000  # first untouched sample is full amplitude
    assert out[99] == 0  # fades out to zero


def test_apply_edge_fades_shorter_than_fade_is_safe():
    sr = 1000
    samples = [500, 500]
    out = struct.unpack(
        "<2h", audio.apply_edge_fades(struct.pack("<2h", *samples), sr, 1, 5.0)
    )
    assert len(out) == 2


def test_concat_wav_sequence_interleaves_silence_in_order(tmp_path):
    sr = 8000
    p1 = tmp_path / "c0.wav"
    p2 = tmp_path / "c1.wav"
    _write_wav(p1, sr, [9000] * int(sr * 0.5))
    _write_wav(p2, sr, [-9000] * int(sr * 0.25))
    sequence = [
        {"type": "speech", "chunk_index": 0},
        {"type": "pause", "duration_sec": 1.0},
        {"type": "speech", "chunk_index": 1},
    ]
    out = tmp_path / "final.wav"
    out_sr, duration = audio.concat_wav_sequence([p1, p2], sequence, out)
    assert out_sr == sr
    assert duration == pytest.approx(0.5 + 1.0 + 0.25, abs=0.01)
    final_sr, samples = _read_samples(out)
    assert final_sr == sr
    # 0.5s speech + 1.0s silence + 0.25s speech
    assert len(samples) == int(sr * 1.75)
    silence = samples[int(sr * 0.5) : int(sr * 1.5)]
    assert all(v == 0 for v in silence)  # exact zero-filled buffer between chunks
    assert samples[0] == 0 and samples[-1] == 0  # edge fades present


def test_concat_wav_sequence_leading_and_trailing_pause(tmp_path):
    sr = 8000
    p1 = tmp_path / "c0.wav"
    _write_wav(p1, sr, [8000] * int(sr * 0.25))
    sequence = [
        {"type": "pause", "duration_sec": 0.5},
        {"type": "speech", "chunk_index": 0},
        {"type": "pause", "duration_sec": 0.75},
    ]
    out = tmp_path / "final.wav"
    _, duration = audio.concat_wav_sequence([p1], sequence, out)
    assert duration == pytest.approx(0.5 + 0.25 + 0.75, abs=0.01)


def test_concat_wav_sequence_rejects_sample_rate_mismatch(tmp_path):
    p1 = tmp_path / "a.wav"
    p2 = tmp_path / "b.wav"
    _write_wav(p1, 8000, [100] * 100)
    _write_wav(p2, 16000, [100] * 100)
    sequence = [
        {"type": "speech", "chunk_index": 0},
        {"type": "pause", "duration_sec": 0.5},
        {"type": "speech", "chunk_index": 1},
    ]
    with pytest.raises(audio.AudioError, match="sample rate mismatch"):
        audio.concat_wav_sequence([p1, p2], sequence, tmp_path / "out.wav")


def test_concat_wav_sequence_rejects_out_of_range_chunk(tmp_path):
    p1 = tmp_path / "a.wav"
    _write_wav(p1, 8000, [100] * 100)
    sequence = [{"type": "speech", "chunk_index": 5}]
    with pytest.raises(audio.AudioError, match="out of range"):
        audio.concat_wav_sequence([p1], sequence, tmp_path / "out.wav")


def test_concat_wav_sequence_rejects_pause_only(tmp_path):
    with pytest.raises(audio.AudioError):
        audio.concat_wav_sequence(
            [], [{"type": "pause", "duration_sec": 1.0}], tmp_path / "o.wav"
        )


# ---------- API: narration jobs carry the pause plan ----------

def test_create_narration_with_pause_tags_builds_sequence(client):
    voice = _approved_voice(client)
    resp = client.post(
        "/api/narrations",
        json={
            "voice_id": voice["id"],
            "title": "Pauses",
            "script": "Hello there. [Pause: 1.5s] Welcome back.",
            "language": "English",
        },
    )
    assert resp.status_code == 201, resp.text
    narration = resp.json()
    assert narration["chunk_count"] == 2

    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    payload = claim["payload"]
    # Tags are stripped from worker text; the stitch plan is present.
    assert payload["chunks"] == ["Hello there.", "Welcome back."]
    assert "[Pause" not in " ".join(payload["chunks"])
    assert payload["sequence"] == [
        {"type": "speech", "chunk_index": 0},
        {"type": "pause", "duration_sec": 1.5},
        {"type": "speech", "chunk_index": 1},
    ]


def test_create_narration_without_pauses_has_no_sequence(client):
    voice = _approved_voice(client)
    client.post(
        "/api/narrations",
        json={"voice_id": voice["id"], "script": "Plain. No tags.", "language": "English"},
    )
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert "sequence" not in claim["payload"]


def test_create_narration_pause_only_script_rejected(client):
    voice = _approved_voice(client)
    resp = client.post(
        "/api/narrations",
        json={
            "voice_id": voice["id"],
            "script": "[Pause: 1s] [Pause: 500ms]",
            "language": "English",
        },
    )
    assert resp.status_code == 422
    assert "speakable" in resp.json()["detail"]


# ---------- API: built-in voice pause splitting ----------

def test_builtin_voice_with_pause_tags_splits_segments(client):
    client.get("/auth/dev-login?email=pauses-builtin@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={
            "speaker": "Vivian",
            "language": "English",
            "script": "Hello [Pause: 1s] world. [Speaker: Ryan] [Pause: 500ms] Hi!",
            "title": "P",
        },
    )
    assert resp.status_code == 201, resp.text
    narration = resp.json()
    # Piece 1 (Vivian pre-pause), piece 2 (Vivian post-pause), piece 3 (Ryan).
    assert narration["chunk_count"] == 3
    segs = narration["dialogue_segments"]
    assert [s["text"] for s in segs] == ["Hello", "world.", "Hi!"]
    assert [s["speaker"] for s in segs] == ["Vivian", "Vivian", "Ryan"]

    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert claim["type"] == "custom_voice"
    payload = claim["payload"]
    assert [s["text"] for s in payload["dialogue_segments"]] == ["Hello", "world.", "Hi!"]
    assert payload["sequence"] == [
        {"type": "speech", "chunk_index": 0},
        {"type": "pause", "duration_sec": 1.0},
        {"type": "speech", "chunk_index": 1},
        # 0.3s turn gap between Vivian and Ryan, then Ryan's 0.5s pause.
        {"type": "gap", "duration_sec": 0.3},
        {"type": "pause", "duration_sec": 0.5},
        {"type": "speech", "chunk_index": 2},
    ]


def test_builtin_voice_without_pauses_has_no_sequence(client):
    client.get("/auth/dev-login?email=pauses-builtin2@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={"speaker": "Vivian", "language": "English", "script": "No tags here.", "title": "P"},
    )
    assert resp.status_code == 201
    claim = client.post("/internal/jobs/poll", headers=WORKER_AUTH).json()
    assert "sequence" not in claim["payload"]


def test_builtin_voice_pause_only_script_rejected(client):
    client.get("/auth/dev-login?email=pauses-builtin3@example.com")
    resp = client.post(
        "/api/builtin-voices/generate",
        json={"speaker": "Vivian", "language": "English", "script": "[Pause: 1s]", "title": "P"},
    )
    assert resp.status_code == 422


# ---------- E2E: silence actually lands in the final WAV ----------

def test_e2e_narration_with_pauses_includes_silence(client):
    mock = MockBackend()
    voice = _approved_voice(client, email="pauses-e2e@example.com")

    narration = client.post(
        "/api/narrations",
        json={
            "voice_id": voice["id"],
            "title": "E2E pauses",
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
    _complete(
        client,
        claim,
        outputs[0].sample_rate,
        [o.duration_sec for o in outputs],
    )

    narration = client.get(f"/api/narrations/{narration['id']}").json()
    assert narration["status"] == "ready"
    audio_resp = client.get(f"/api/files/narrations/{narration['id']}/audio")
    assert audio_resp.status_code == 200
    assert audio_resp.content[:4] == b"RIFF"

    with wave.open(io.BytesIO(audio_resp.content), "rb") as wf:
        sr = wf.getframerate()
        n_frames = wf.getnframes()
    speech_sec = sum(o.duration_sec for o in outputs)
    # Final duration = speech + the 1s pause (within float rounding).
    assert n_frames / sr == pytest.approx(speech_sec + 1.0, abs=0.05)
    assert narration["duration_sec"] == pytest.approx(speech_sec + 1.0, abs=0.05)
