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

The tensor shapes (108, 16) and (2048,) are specific to the 12 Hz tokenizer of
qwen-tts==0.1.1, the pinned, notebook-installed version
(reference/Voice_Studio.ipynb cell 7). Validation is strict by default so a
corrupt or version-mismatched prompt is rejected before it reaches the model;
pass ``strict_shapes=False`` only if a future qwen-tts version changes the
shapes.

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

# Shapes proven by notebook cell 27 for the qwen-tts==0.1.1 12 Hz tokenizer.
REF_CODE_SHAPE = (108, 16)
REF_SPK_EMBEDDING_SHAPE = (2048,)
SCHEMA_VERSION = "qwen-tts==0.1.1 (Qwen3-TTS-12Hz tokenizer)"


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


def validate_saved_prompt(saved_prompt: dict, *, strict_shapes: bool = True) -> None:
    """Validate a saved prompt dict against the notebook cell-25 contract.

    With ``strict_shapes=True`` (default) tensor shapes must match the
    qwen-tts==0.1.1 12 Hz tokenizer exactly. Types are always checked.
    """
    if not isinstance(saved_prompt, dict):
        raise ValueError("saved prompt must be a dict")
    missing = [key for key in EXPECTED_KEYS if key not in saved_prompt]
    if missing:
        raise ValueError(f"saved prompt missing key(s): {missing}")

    ref_code = saved_prompt["ref_code"]
    ref_spk = saved_prompt["ref_spk_embedding"]
    icl_mode = saved_prompt["icl_mode"]
    xvec = saved_prompt["x_vector_only_mode"]
    ref_text = saved_prompt["ref_text"]

    shape_ref = tuple(ref_code.shape) if hasattr(ref_code, "shape") else None
    if shape_ref is None:
        raise ValueError("ref_code must be a tensor with a shape")
    if strict_shapes:
        if shape_ref != REF_CODE_SHAPE:
            raise ValueError(
                f"ref_code shape mismatch: got {shape_ref}, expected "
                f"{REF_CODE_SHAPE} for {SCHEMA_VERSION}"
            )
    elif len(shape_ref) != 2:
        raise ValueError(f"ref_code must be 2D, got {shape_ref}")

    shape_spk = tuple(ref_spk.shape) if hasattr(ref_spk, "shape") else None
    if shape_spk is None:
        raise ValueError("ref_spk_embedding must be a tensor with a shape")
    if strict_shapes:
        if shape_spk != REF_SPK_EMBEDDING_SHAPE:
            raise ValueError(
                f"ref_spk_embedding shape mismatch: got {shape_spk}, expected "
                f"{REF_SPK_EMBEDDING_SHAPE} for {SCHEMA_VERSION}"
            )
    elif len(shape_spk) != 1:
        raise ValueError(f"ref_spk_embedding must be 1D, got {shape_spk}")

    if not isinstance(icl_mode, bool):
        raise ValueError(f"icl_mode must be a bool, got {type(icl_mode).__name__}")
    if not isinstance(xvec, bool):
        raise ValueError(
            f"x_vector_only_mode must be a bool, got {type(xvec).__name__}"
        )
    if ref_text is not None and not isinstance(ref_text, str):
        raise ValueError(
            f"ref_text must be a str or None, got {type(ref_text).__name__}"
        )
    if icl_mode and not isinstance(ref_text, str):
        # Notebook cell 27 asserts ref_text is a str for the ICL-mode prompts
        # this worker produces (x_vector_only_mode=False).
        raise ValueError("ref_text must be a str when icl_mode is True")
