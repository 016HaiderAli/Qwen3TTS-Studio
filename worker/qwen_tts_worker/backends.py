"""Inference backend interface and the deterministic mock implementation.

The GPU worker runs one of these backends behind the same HTTP contract. The
mock backend requires no GPU, no torch and no qwen-tts, so the full web-tier
workflow can be validated in a GPU-less environment. The mock records the
delivery direction so end-to-end tests can assert it flows through.
"""
import hashlib
import io
import math
import struct
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SynthesisOutput:
    """One generated WAV."""

    wav_bytes: bytes
    sample_rate: int
    duration_sec: float


class InferenceBackend(ABC):
    name: str = "base"

    @abstractmethod
    def design(self, *, language: str, instruct: str, text: str) -> SynthesisOutput:
        """Generate a reference/design clip for a voice description."""

    @abstractmethod
    def create_clone_prompt(self, *, ref_audio_b64: str, ref_text: str, language: str) -> bytes:
        """Return a serialized voice-clone prompt (.pt bytes) for the reference audio."""

    @abstractmethod
    def narrate(
        self,
        *,
        chunks: list[str],
        prompt_pt_b64: str,
        language: str,
        instruct: str,
        ref_audio_b64: str = "",
        ref_text: str = "",
        voice_setting: dict | None = None,
    ) -> list[SynthesisOutput]:
        """Generate one WAV per chunk using the voice-clone prompt.

        ``prompt_pt_b64`` — base64-encoded serialized clone prompt (.pt). When
        empty/absent the worker must fall back to ``ref_audio_b64`` (zero-shot
        path) or raise a descriptive ValueError.
        ``ref_audio_b64`` — base64-encoded reference WAV for zero-shot synthesis.
        ``ref_text`` — the reference transcript, embedding guidance only; must
        stay empty when no transcript was saved (Qwen treats it as optional).
        """

    @abstractmethod
    def generate_custom_voice(
        self,
        *,
        chunks: list[str],
        speaker: str,
        language: str,
        instruct: str,
        dialogue_segments: list[dict] | None = None,
        voice_setting: dict | None = None,
    ) -> list[SynthesisOutput]:
        """Generate one WAV per chunk (single-speaker) or per segment (dialogue)."""


def _hash_int(*parts: str) -> int:
    h = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(h, 16)


def make_wav(sample_rate: int, samples: list[float]) -> bytes:
    """Encode float samples in [-1, 1] as a mono 16-bit PCM WAV."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for s in samples:
            clipped = max(-1.0, min(1.0, s))
            frames += struct.pack("<h", int(clipped * 32767))
        wf.writeframes(bytes(frames))
    return buf.getvalue()


class MockBackend(InferenceBackend):
    """Deterministic synthetic audio. No GPU, no model weights."""

    name = "mock"

    def __init__(self, sample_rate: int = 24000):
        self.sample_rate = sample_rate

    @staticmethod
    def _setting(voice_setting: dict | None, key: str, default):
        if not voice_setting:
            return default
        return voice_setting.get(key, default)

    def _tone(
        self,
        seed: int,
        duration_sec: float,
        base_freq: float = 220.0,
        vol: float = 1.0,
        pitch_st: int = 0,
    ) -> SynthesisOutput:
        sr = self.sample_rate
        # Phase 7B: semitone shift multiplies the base frequency; volume scales
        # amplitude; speed shortens the clip (encoded by the caller in the
        # requested duration).
        freq_factor = 2 ** (pitch_st / 12.0)
        n = int(sr * duration_sec)
        # Two overlapping sines: pitch encodes seed (incl. delivery direction);
        # amplitude envelope avoids clicks.
        f1 = (base_freq + (seed % 400)) * freq_factor
        f2 = (base_freq * 1.5 + (seed % 137)) * freq_factor
        samples = []
        for i in range(n):
            t = i / sr
            env = min(1.0, t / 0.05) * min(1.0, (duration_sec - t) / 0.05)
            v = 0.35 * math.sin(2 * math.pi * f1 * t) + 0.25 * math.sin(
                2 * math.pi * f2 * t
            )
            samples.append(max(-1.0, min(1.0, v * max(0.0, env)) * vol))
        return SynthesisOutput(make_wav(sr, samples), sr, duration_sec)

    def design(self, *, language: str, instruct: str, text: str) -> SynthesisOutput:
        seed = _hash_int("design", language, instruct, text)
        duration = 2.0 + (len(text) % 30) / 10.0
        return self._tone(seed, duration, base_freq=200.0)

    def create_clone_prompt(self, *, ref_audio_b64: str, ref_text: str, language: str) -> bytes:
        # The mock prompt is a plain text bundle (no torch). The real worker
        # produces a torch-serialized dict with the notebook cell-25 schema.
        seed = _hash_int("prompt", ref_audio_b64[:256], ref_text, language)
        return f"mock-prompt::{seed}".encode("utf-8")

    def narrate(
        self,
        *,
        chunks: list[str],
        prompt_pt_b64: str,
        language: str,
        instruct: str,
        ref_audio_b64: str = "",
        ref_text: str = "",
        voice_setting: dict | None = None,
    ) -> list[SynthesisOutput]:
        # The mock generates deterministic synthetic audio regardless of which
        # path (pre-baked prompt vs. zero-shot reference) the real backend would
        # take. ref_audio_b64 and ref_text are accepted for interface parity but
        # are not used; prompt_pt_b64 still seeds the tone for test assertions.
        speed = float(self._setting(voice_setting, "speed", 1.0))
        vol = float(self._setting(voice_setting, "vol", 1.0))
        pitch_st = int(self._setting(voice_setting, "pitch", 0))
        emotion = self._setting(voice_setting, "emotion", "neutral")
        outputs = []
        for i, chunk in enumerate(chunks):
            seed = _hash_int(
                "narration", str(i), chunk, instruct, emotion, language, prompt_pt_b64[:64]
            )
            base_dur = 1.2 + (len(chunk.split()) / 80.0) * 2.4
            if "\n\n" in chunk:
                base_dur += 0.4
            base_dur = base_dur / max(speed, 0.1)
            outputs.append(
                self._tone(seed, base_dur, base_freq=220.0 + i * 25, vol=vol, pitch_st=pitch_st)
            )
        return outputs

    def generate_custom_voice(
        self,
        *,
        chunks: list[str],
        speaker: str,
        language: str,
        instruct: str,
        dialogue_segments: list[dict] | None = None,
        voice_setting: dict | None = None,
    ) -> list[SynthesisOutput]:
        speed = float(self._setting(voice_setting, "speed", 1.0))
        vol = float(self._setting(voice_setting, "vol", 1.0))
        pitch_st = int(self._setting(voice_setting, "pitch", 0))
        emotion = self._setting(voice_setting, "emotion", "neutral")
        outputs = []
        if dialogue_segments:
            for i, seg in enumerate(dialogue_segments):
                seg_speaker = seg.get("speaker", speaker)
                seg_text = seg.get("text", "")
                seg_instruct = seg.get("instruct", "")
                seed = _hash_int(
                    "dialogue", seg_speaker, str(i), seg_text, seg_instruct, emotion, language,
                )
                base_dur = 1.2 + (len(seg_text.split()) / 80.0) * 2.4
                if "\n\n" in seg_text:
                    base_dur += 0.4
                base_dur = base_dur / max(speed, 0.1)
                outputs.append(
                    self._tone(
                        seed, base_dur, base_freq=180.0 + i * 15, vol=vol, pitch_st=pitch_st
                    )
                )
        else:
            for i, chunk in enumerate(chunks):
                seed = _hash_int(
                    "custom_voice", speaker, str(i), chunk, instruct, emotion, language
                )
                base_dur = 1.2 + (len(chunk.split()) / 80.0) * 2.4
                if "\n\n" in chunk:
                    base_dur += 0.4
                base_dur = base_dur / max(speed, 0.1)
                outputs.append(
                    self._tone(
                        seed, base_dur, base_freq=180.0 + i * 15, vol=vol, pitch_st=pitch_st
                    )
                )
        return outputs
