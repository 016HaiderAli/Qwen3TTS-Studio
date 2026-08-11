"""Voice-clone prompt serialization.

Implements the exact persistence schema proven in reference/Voice_Studio.ipynb
cells 25, 27 and 29:

    saved_prompt = {
        "icl_mode": bool,
        "ref_code": torch.Tensor(108, 16),          # CPU, detached
        "ref_spk_embedding": torch.Tensor(2048,),   # CPU, detached
        "ref_text": str,
        "x_vector_only_mode": bool,
    }

saved via torch.save and restored via
``qwen_tts.inference.qwen3_tts_model.VoiceClonePromptItem``.

torch is imported lazily so this module can be imported (and structurally
tested) without torch installed.
"""
import io
import importlib.util

EXPECTED_KEYS = (
    "icl_mode",
    "ref_code",
    "ref_spk_embedding",
    "ref_text",
    "x_vector_only_mode",
)


def torch_available() -> bool:
    return importlib.util.find_spec("torch") is not None


def require_torch():
    if not torch_available():
        raise ImportError(
            "torch is required for this operation; install the qwen worker "
            "dependencies (requirements-qwen.txt) on the GPU host."
        )
    import torch  # noqa: F401

    return torch


def build_saved_prompt(prompt_item) -> dict:
    """Convert a VoiceClonePromptItem into the notebook cell-25 dict.

    Tensors are detached and moved to CPU so the saved file is GPU-independent.
    """
    return {
        "icl_mode": bool(prompt_item.icl_mode),
        "ref_code": prompt_item.ref_code.detach().cpu(),
        "ref_spk_embedding": prompt_item.ref_spk_embedding.detach().cpu(),
        "ref_text": prompt_item.ref_text,
        "x_vector_only_mode": bool(prompt_item.x_vector_only_mode),
    }


def serialize_prompt(saved_prompt: dict) -> bytes:
    torch = require_torch()
    validate_saved_prompt(saved_prompt)
    buffer = io.BytesIO()
    torch.save(saved_prompt, buffer)
    return buffer.getvalue()


def deserialize_prompt(data: bytes) -> dict:
    torch = require_torch()
    buffer = io.BytesIO(data)
    saved = torch.load(buffer, map_location="cpu", weights_only=True)
    validate_saved_prompt(saved)
    return saved


def restore_prompt_item(saved_prompt: dict, device):
    """Restore a VoiceClonePromptItem from the saved dict (notebook cell 29)."""
    torch = require_torch()
    from qwen_tts.inference.qwen3_tts_model import VoiceClonePromptItem

    validate_saved_prompt(saved_prompt)
    return VoiceClonePromptItem(
        ref_code=saved_prompt["ref_code"].to(device),
        ref_spk_embedding=saved_prompt["ref_spk_embedding"].to(device),
        x_vector_only_mode=saved_prompt["x_vector_only_mode"],
        icl_mode=saved_prompt["icl_mode"],
        ref_text=saved_prompt["ref_text"],
    )


def validate_saved_prompt(saved_prompt: dict) -> None:
    if not isinstance(saved_prompt, dict):
        raise ValueError("saved prompt must be a dict")
    for key in EXPECTED_KEYS:
        if key not in saved_prompt:
            raise ValueError(f"saved prompt missing key: {key}")
    ref_code = saved_prompt["ref_code"]
    spk = saved_prompt["ref_spk_embedding"]
    shape_ref = tuple(ref_code.shape) if hasattr(ref_code, "shape") else None
    shape_spk = tuple(spk.shape) if hasattr(spk, "shape") else None
    if shape_ref is not None and len(shape_ref) != 2:
        raise ValueError(f"ref_code must be 2D, got {shape_ref}")
    if shape_spk is not None and len(shape_spk) != 1:
        raise ValueError(f"ref_spk_embedding must be 1D, got {shape_spk}")
