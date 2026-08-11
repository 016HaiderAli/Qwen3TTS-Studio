"""Tests for the voice-clone prompt schema (notebook cell-25 contract).

torch is not installed in the dev environment, so these tests validate the
schema shape contract with lightweight stand-ins and confirm lazy imports.
"""
import pytest

from qwen_tts_worker import prompt as prompt_mod


class _FakeTensor:
    def __init__(self, shape):
        self.shape = shape


def test_torch_lazy_import():
    # In the dev environment torch is not installed; availability is discovered
    # lazily and never imported at package import time.
    assert prompt_mod.torch_available() is False
    with pytest.raises(ImportError):
        prompt_mod.require_torch()


def test_validate_saved_prompt_accepts_correct_schema():
    saved = {
        "icl_mode": False,
        "ref_code": _FakeTensor((108, 16)),
        "ref_spk_embedding": _FakeTensor((2048,)),
        "ref_text": "reference transcript",
        "x_vector_only_mode": False,
    }
    prompt_mod.validate_saved_prompt(saved)  # should not raise


def test_validate_saved_prompt_missing_key():
    with pytest.raises(ValueError, match="missing key"):
        prompt_mod.validate_saved_prompt({"icl_mode": False})


def test_validate_saved_prompt_rejects_bad_shapes():
    with pytest.raises(ValueError, match="ref_code must be 2D"):
        prompt_mod.validate_saved_prompt(
            {
                "icl_mode": False,
                "ref_code": _FakeTensor((108,)),
                "ref_spk_embedding": _FakeTensor((2048,)),
                "ref_text": "t",
                "x_vector_only_mode": False,
            }
        )
