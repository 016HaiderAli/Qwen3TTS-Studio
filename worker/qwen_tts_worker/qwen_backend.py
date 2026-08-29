"""Real Qwen3-TTS inference backend.

This is the ONLY module in the repository that imports ``qwen_tts``/PyTorch.
It wraps exactly the workflow proven in reference/Voice_Studio.ipynb:

  - VoiceDesign model: ``generate_voice_design(text, language, instruct)`` (cell 15)
  - Base model:        ``create_voice_clone_prompt(ref_audio=str(path), ref_text)`` (cell 21)
  - Base model:        ``generate_voice_clone(text, language, voice_clone_prompt)`` (cell 32/36)

The module imports torch/qwen-tts lazily, so importing the worker package does
not require a GPU environment. GPU inference has NOT been validated in the
current development environment; this code is the interface the real GPU host
runs, mirroring the notebook calls. Run ``qwen_tts_worker.checks.run_startup_checks``
before starting the worker for actionable environment diagnostics.

Model lifecycle (one Qwen model resident at a time, mirroring notebook cells
11/17): the Base model stays loaded across clone-prompt/narration jobs; the
VoiceDesign model is loaded only while a design job runs and then released
(``del`` + ``gc.collect()`` + ``torch.cuda.empty_cache()``). A single 1.7B
checkpoint is the safe default on a T4; VRAM budgets beyond that are NOT assumed.
"""
import base64
import io
import logging
import tempfile
from pathlib import Path

from .backends import InferenceBackend, SynthesisOutput
from .config import WorkerConfig
from .prompt import (
    build_saved_prompt,
    deserialize_prompt,
    restore_prompt_item,
    serialize_prompt,
)

logger = logging.getLogger("qwen-worker")


def _wav_bytes(wavs, sr: int) -> bytes:
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
        self._custom_voice_model = None

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

    def _load_custom_voice(self):
        import torch
        from qwen_tts import Qwen3TTSModel

        if self._custom_voice_model is not None:
            return self._custom_voice_model
        logger.info("Loading CustomVoice model %s ...", self.config.qwen_model_custom_voice)
        self._custom_voice_model = Qwen3TTSModel.from_pretrained(
            self.config.qwen_model_custom_voice,
            device_map=self.config.qwen_device,
            dtype=getattr(torch, self.config.qwen_dtype),
        )
        logger.info("CustomVoice model loaded")
        return self._custom_voice_model

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
        """Free the VoiceDesign model from VRAM (notebook cell 17 discipline).

        If ``QWEN_KEEP_DESIGN_LOADED`` is set, the model intentionally stays
        resident and may coexist with the Base model on later narration jobs;
        that combination is the operator's explicit choice and is NOT assumed
        to fit without verification.
        """
        if self._design_model is None:
            return
        if self.config.qwen_keep_design_loaded:
            logger.warning(
                "QWEN_KEEP_DESIGN_LOADED=true keeps VoiceDesign resident; when "
                "the Base model is later loaded for narration both checkpoints "
                "share VRAM. Confirm the GPU actually fits both before using this."
            )
            return
        import gc

        logger.info("Releasing VoiceDesign model from GPU")
        self._design_model = None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except ImportError:  # pragma: no cover - only reached if torch vanished mid-run
            pass

    # ---------- InferenceBackend ----------
    def design(self, *, language: str, instruct: str, text: str) -> SynthesisOutput:
        import torch

        try:
            design_model = self._load_design()
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
        # Notebook cell 21 proves the filesystem-path form:
        #   create_voice_clone_prompt(ref_audio=str(reference_path), ref_text=...)
        # qwen-tts loads str paths via librosa (native sample rate, mono). Decode
        # the reference clip to a temp WAV and pass the path rather than a numpy
        # tuple, exactly matching the proven notebook call.
        with tempfile.TemporaryDirectory(prefix="qwen-ref-") as tmpdir:
            ref_path = Path(tmpdir) / "reference.wav"
            sf.write(ref_path, wav, int(sr), format="WAV")
            prompt_items = model.create_voice_clone_prompt(
                ref_audio=str(ref_path),
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

        if instruct and instruct.strip():
            logger.info(
                "delivery direction received for narration, but qwen-tts==0.1.1 "
                "`generate_voice_clone` has no `instruct` parameter, so it is not "
                "forwarded (an unsupported kwarg would raise TypeError). The "
                "direction already shaped the reference voice at design time; "
                "narration prosody follows the native punctuation/paragraph path "
                "of the Base model (see docs/DEVIATIONS.md §1)."
            )

        outputs: list[SynthesisOutput] = []
        for i, chunk in enumerate(chunks):
            logger.info("Generating chunk %d/%d", i + 1, len(chunks))
            with torch.inference_mode():
                wavs, sr = model.generate_voice_clone(
                    text=chunk,
                    language=language,
                    voice_clone_prompt=prompt_list,
                )
            data = _wav_bytes(wavs[0], sr)
            duration = len(wavs[0]) / sr
            outputs.append(
                SynthesisOutput(data, int(sr), round(float(duration), 3))
            )
        return outputs

    def generate_custom_voice(
        self,
        *,
        chunks: list[str],
        speaker: str,
        language: str,
        instruct: str,
    ) -> list[SynthesisOutput]:
        import torch

        model = self._load_custom_voice()
        outputs: list[SynthesisOutput] = []
        for i, chunk in enumerate(chunks):
            logger.info(
                "custom_voice job: speaker=%s chunk %d/%d",
                speaker, i + 1, len(chunks),
            )
            with torch.inference_mode():
                wavs, sr = model.generate_custom_voice(
                    text=chunk,
                    language=language,
                    speaker=speaker,
                    instruct=instruct if instruct.strip() else None,
                )
            data = _wav_bytes(wavs[0], sr)
            duration = len(wavs[0]) / sr
            outputs.append(
                SynthesisOutput(data, int(sr), round(float(duration), 3))
            )
        return outputs
