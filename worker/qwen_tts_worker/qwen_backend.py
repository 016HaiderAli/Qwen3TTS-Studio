"""Real Qwen3-TTS inference backend.

This is the ONLY module in the repository that imports ``qwen_tts``/PyTorch.
It wraps exactly the workflow proven in reference/Voice_Studio.ipynb:

  - VoiceDesign model: ``generate_voice_design(text, language, instruct)``
  - Base model:        ``create_voice_clone_prompt(ref_audio, ref_text)``
  - Base model:        ``generate_voice_clone(text, language, voice_clone_prompt)``

The module imports torch/qwen-tts lazily, so importing the worker package does
not require a GPU environment. GPU inference has NOT been validated in the
current development environment; this code is the interface the real GPU host
runs, mirroring the notebook calls.
"""
import base64
import inspect
import io
import logging
from typing import Any

from .backends import InferenceBackend, SynthesisOutput
from .config import WorkerConfig
from .prompt import (
    build_saved_prompt,
    deserialize_prompt,
    restore_prompt_item,
    serialize_prompt,
)

logger = logging.getLogger("qwen-worker")


def _wav_bytes(wavs: Any, sr: int) -> bytes:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, wavs, sr, format="WAV")
    return buffer.getvalue()


class QwenBackend(InferenceBackend):
    """GPU-backed Qwen3-TTS backend. Requires CUDA + qwen-tts (see requirements-qwen.txt)."""

    name = "qwen"

    def __init__(self, config: WorkerConfig):
        self.config = config
        self._base_model = None
        self._design_model = None
        self._clone_instruct_probe = None

    # ---------- model lifecycle (notebook cells 11/17/19) ----------
    def _load_base(self):
        import torch
        from qwen_tts import Qwen3TTSModel

        if self._base_model is not None:
            return self._base_model
        logger.info("Loading Base model %s ...", self.config.qwen_model_base)
        self._base_model = Qwen3TTSModel.from_pretrained(
            self.config.qwen_model_base,
            device_map=self.config.qwen_device,
            dtype=getattr(torch, self.config.qwen_dtype),
        )
        logger.info("Base model loaded on %s", self.config.qwen_device)
        return self._base_model

    def _load_design(self):
        import torch
        from qwen_tts import Qwen3TTSModel

        if self._design_model is not None:
            return self._design_model
        logger.info("Loading VoiceDesign model %s ...", self.config.qwen_model_design)
        self._design_model = Qwen3TTSModel.from_pretrained(
            self.config.qwen_model_design,
            device_map=self.config.qwen_device,
            dtype=getattr(torch, self.config.qwen_dtype),
        )
        logger.info("VoiceDesign model loaded")
        return self._design_model

    def _release_design(self) -> None:
        """Free the VoiceDesign model from VRAM (notebook cell 17 discipline)."""
        if self._design_model is not None and not self.config.qwen_keep_design_loaded:
            import gc

            import torch

            logger.info("Releasing VoiceDesign model from GPU")
            self._design_model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()

    def _model_device(self):
        import torch

        return torch.device(self.config.qwen_device)

    # ---------- InferenceBackend ----------
    def design(self, *, language: str, instruct: str, text: str) -> SynthesisOutput:
        design_model = self._load_design()
        try:
            import torch

            with torch.inference_mode():
                wavs, sr = design_model.generate_voice_design(
                    text=text,
                    language=language,
                    instruct=instruct,
                )
        finally:
            self._release_design()
        data = _wav_bytes(wavs[0], sr)
        duration = len(wavs[0]) / sr
        return SynthesisOutput(data, int(sr), round(float(duration), 3))

    def create_clone_prompt(self, *, ref_audio_b64: str, ref_text: str, language: str) -> bytes:
        import numpy as np
        import soundfile as sf

        model = self._load_base()
        raw = base64.b64decode(ref_audio_b64)
        wav, sr = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
        if wav.ndim > 1:
            wav = np.mean(wav, axis=-1).astype(np.float32)
        prompt_items = model.create_voice_clone_prompt(
            ref_audio=(wav, int(sr)),
            ref_text=ref_text,
            x_vector_only_mode=False,
        )
        saved = build_saved_prompt(prompt_items[0])
        return serialize_prompt(saved)

    def narrate(
        self,
        *,
        chunks: list[str],
        prompt_pt_b64: str,
        language: str,
        instruct: str,
    ) -> list[SynthesisOutput]:
        import torch

        model = self._load_base()
        saved = deserialize_prompt(base64.b64decode(prompt_pt_b64))
        device = next(model.model.parameters()).device
        prompt_item = restore_prompt_item(saved, device)
        prompt_list = [prompt_item]

        clone_kwargs: dict[str, Any] = {}
        if instruct and instruct.strip():
            clone_kwargs = self._probe_instruct_arg()
            if "instruct" in clone_kwargs:
                clone_kwargs["instruct"] = instruct.strip()
            else:
                logger.warning(
                    "Installed generate_voice_clone does not accept `instruct`; "
                    "delivery direction is preserved (native punctuation/prosody path)."
                )

        outputs: list[SynthesisOutput] = []
        for i, chunk in enumerate(chunks):
            logger.info("Generating chunk %d/%d", i + 1, len(chunks))
            with torch.inference_mode():
                wavs, sr = model.generate_voice_clone(
                    text=chunk,
                    language=language,
                    voice_clone_prompt=prompt_list,
                    **clone_kwargs,
                )
            data = _wav_bytes(wavs[0], sr)
            duration = len(wavs[0]) / sr
            outputs.append(
                SynthesisOutput(data, int(sr), round(float(duration), 3))
            )
        return outputs

    def _probe_instruct_arg(self) -> dict[str, Any]:
        """Forward-compatible capability probe: does generate_voice_clone accept instruct?"""
        if self._clone_instruct_probe is not None:
            return {"instruct": ""} if self._clone_instruct_probe else {}
        model = self._load_base()
        sig = inspect.signature(model.generate_voice_clone)
        supports = "instruct" in sig.parameters
        self._clone_instruct_probe = supports
        logger.info("generate_voice_clone instruct support: %s", supports)
        return {"instruct": ""} if supports else {}
