"""Tests for the voice-clone prompt schema (notebook cell-25 contract).

torch is not installed in the dev environment, so these tests validate the
schema shape contract with lightweight stand-ins and confirm lazy imports.
"""
import pytest

from qwen_tts_worker import prompt as prompt_mod


class _FakeTensor:
    def __init__(self, shape):
        self.shape = shape


def _saved(**overrides):
    base = {
        "icl_mode": True,
        "ref_code": _FakeTensor((108, 16)),
        "ref_spk_embedding": _FakeTensor((2048,)),
        "ref_text": "reference transcript",
        "x_vector_only_mode": False,
    }
    base.update(overrides)
    return base


def test_torch_lazy_import():
    # In the dev environment torch is not installed; availability is discovered
    # lazily and never imported at package import time.
    assert prompt_mod.torch_available() is False
    with pytest.raises(ImportError):
        prompt_mod.require_torch()


def test_schema_version_constants_match_notebook():
    # The qwen-tts==0.1.1 12 Hz tokenizer uses 16 quantizers; ref_code is
    # (T, 16) with the frame count T duration-dependent (real T4 run: 107).
    assert prompt_mod.REF_CODE_QUANTIZERS == 16
    assert prompt_mod.REF_SPK_EMBEDDING_SHAPE == (2048,)
    assert prompt_mod.SCHEMA_VERSION.startswith("qwen-tts==0.1.1")


def test_validate_saved_prompt_accepts_correct_schema():
    prompt_mod.validate_saved_prompt(_saved())  # should not raise


@pytest.mark.parametrize("frames", [107, 108, 2048])
def test_validate_saved_prompt_accepts_duration_dependent_ref_code(frames):
    # T grows with the reference-audio duration; any T >= 1 with 16 columns is
    # a valid ref_code (107 is what the real T4 run produced).
    prompt_mod.validate_saved_prompt(_saved(ref_code=_FakeTensor((frames, 16))))


def test_validate_saved_prompt_missing_key():
    with pytest.raises(ValueError, match="missing key"):
        prompt_mod.validate_saved_prompt({"icl_mode": False})


def test_validate_saved_prompt_rejects_1d_ref_code():
    with pytest.raises(ValueError, match="ref_code must be 2D"):
        prompt_mod.validate_saved_prompt(_saved(ref_code=_FakeTensor((108,))))


def test_validate_saved_prompt_rejects_3d_ref_code():
    with pytest.raises(ValueError, match="ref_code must be 2D"):
        prompt_mod.validate_saved_prompt(_saved(ref_code=_FakeTensor((1, 108, 16))))


def test_validate_saved_prompt_rejects_zero_length_ref_code():
    with pytest.raises(ValueError, match="at least one code frame"):
        prompt_mod.validate_saved_prompt(_saved(ref_code=_FakeTensor((0, 16))))


def test_validate_saved_prompt_rejects_wrong_quantizer_count():
    with pytest.raises(ValueError, match="quantizer columns"):
        prompt_mod.validate_saved_prompt(_saved(ref_code=_FakeTensor((108, 32))))


def test_validate_saved_prompt_rejects_bad_ref_spk_shape():
    with pytest.raises(ValueError, match=r"ref_spk_embedding shape mismatch.*\(2048, 1\)"):
        prompt_mod.validate_saved_prompt(
            _saved(ref_spk_embedding=_FakeTensor((2048, 1)))
        )


def test_validate_saved_prompt_lenient_mode_allows_structurally_different_ref_code():
    # Future qwen-tts versions may change dimensions; lenient mode only checks rank.
    prompt_mod.validate_saved_prompt(
        _saved(ref_code=_FakeTensor((108, 32))), strict_shapes=False
    )


def test_validate_saved_prompt_lenient_mode_rejects_wrong_rank():
    with pytest.raises(ValueError, match="ref_code must be 2D"):
        prompt_mod.validate_saved_prompt(
            _saved(ref_code=_FakeTensor((108,))), strict_shapes=False
        )
    with pytest.raises(ValueError, match="ref_spk_embedding must be 1D"):
        prompt_mod.validate_saved_prompt(
            _saved(ref_spk_embedding=_FakeTensor((2048, 1))), strict_shapes=False
        )


def test_validate_saved_prompt_rejects_non_bool_flags():
    with pytest.raises(ValueError, match="icl_mode must be a bool"):
        prompt_mod.validate_saved_prompt(_saved(icl_mode="yes"))
    with pytest.raises(ValueError, match="x_vector_only_mode must be a bool"):
        prompt_mod.validate_saved_prompt(_saved(x_vector_only_mode=1))


def test_validate_saved_prompt_rejects_non_string_ref_text():
    with pytest.raises(ValueError, match="ref_text must be a str or None"):
        prompt_mod.validate_saved_prompt(_saved(ref_text=123))


def test_validate_saved_prompt_requires_ref_text_when_icl_mode():
    # Notebook cell 27 asserts ref_text is a str for the prompts we produce.
    with pytest.raises(ValueError, match="ref_text must be a str when icl_mode is True"):
        prompt_mod.validate_saved_prompt(_saved(ref_text=None))
    # x-vector-only mode may omit the reference transcript.
    prompt_mod.validate_saved_prompt(
        _saved(icl_mode=False, x_vector_only_mode=True, ref_text=None)
    )
