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
    ) -> list[SynthesisOutput]:
        """Generate one WAV per chunk using the voice-clone prompt."""

    @abstractmethod
    def generate_custom_voice(
        self,
        *,
        chunks: list[str],
        speaker: str,
        language: str,
        instruct: str,
    ) -> list[SynthesisOutput]:
        """Generate one WAV per chunk using a Qwen CustomVoice speaker."""


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

    def _tone(self, seed: int, duration_sec: float, base_freq: float = 220.0) -> SynthesisOutput:
        sr = self.sample_rate
        n = int(sr * duration_sec)
        # Two overlapping sines: pitch encodes seed (incl. delivery direction);
        # amplitude envelope avoids clicks.
        f1 = base_freq + (seed % 400)
        f2 = base_freq * 1.5 + (seed % 137)
        samples = []
        for i in range(n):
            t = i / sr
            env = min(1.0, t / 0.05) * min(1.0, (duration_sec - t) / 0.05)
            v = 0.35 * math.sin(2 * math.pi * f1 * t) + 0.25 * math.sin(
                2 * math.pi * f2 * t
            )
            samples.append(max(-1.0, min(1.0, v * max(0.0, env))))
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
    ) -> list[SynthesisOutput]:
        outputs = []
        for i, chunk in enumerate(chunks):
            seed = _hash_int("narration", str(i), chunk, instruct, language, prompt_pt_b64[:64])
            base_dur = 1.2 + (len(chunk.split()) / 80.0) * 2.4
            if "\n\n" in chunk:
                base_dur += 0.4
            outputs.append(self._tone(seed, base_dur, base_freq=220.0 + i * 25))
        return outputs

    def generate_custom_voice(
        self,
        *,
        chunks: list[str],
        speaker: str,
        language: str,
        instruct: str,
    ) -> list[SynthesisOutput]:
        outputs = []
        for i, chunk in enumerate(chunks):
            seed = _hash_int("custom_voice", speaker, str(i), chunk, instruct, language)
            base_dur = 1.2 + (len(chunk.split()) / 80.0) * 2.4
            if "\n\n" in chunk:
                base_dur += 0.4
            outputs.append(self._tone(seed, base_dur, base_freq=180.0 + i * 15))
        return outputs
