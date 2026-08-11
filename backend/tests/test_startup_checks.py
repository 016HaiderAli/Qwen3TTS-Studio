"""Tests for the GPU-worker startup checks (no GPU/torch/qwen-tts needed).

torch and qwen-tts are not installed here; each test injects lightweight fakes
or simulates import failures via the monkeypatchable ``_import_*`` helpers.
"""
import types

import pytest

from qwen_tts_worker import checks
from qwen_tts_worker.config import WorkerConfig


def _fake_torch(**attrs):
    fake = types.SimpleNamespace(cuda=types.SimpleNamespace())
    for key, value in attrs.items():
        setattr(fake, key, value)
    return fake


def _fake_qwen(version="0.1.1", model_cls=None):
    qwen = types.SimpleNamespace(__version__=version)
    if model_cls is None:
        model_cls = types.SimpleNamespace(
            from_pretrained=lambda **k: None,
            generate_voice_design=lambda **k: None,
            create_voice_clone_prompt=lambda **k: None,
            generate_voice_clone=lambda **k: None,
        )
    return qwen, model_cls


def _fail(name):
    def _raise(*_a, **_k):
        raise ImportError(f"No module named '{name}'")

    return _raise


def test_torch_missing_fails(monkeypatch):
    monkeypatch.setattr(checks, "_import_torch", _fail("torch"))
    result = checks.check_torch_installed()
    assert result.ok is False
    assert "requirements-qwen.txt" in result.message


def test_cuda_unavailable_fails(monkeypatch):
    fake = _fake_torch(__version__="2.11.0")
    fake.cuda.is_available = lambda: False
    monkeypatch.setattr(checks, "_import_torch", lambda: fake)
    result = checks.check_cuda_available()
    assert result.ok is False
    assert "torch.cuda.is_available() is False" in result.message


def test_cuda_available_passes(monkeypatch):
    fake = _fake_torch(__version__="2.11.0")
    fake.cuda.is_available = lambda: True
    fake.cuda.get_device_name = lambda _i: "Tesla T4"
    monkeypatch.setattr(checks, "_import_torch", lambda: fake)
    result = checks.check_cuda_available()
    assert result.ok is True
    assert "Tesla T4" in result.message


def test_device_index_valid(monkeypatch):
    fake = _fake_torch()
    fake.cuda.device_count = lambda: 1
    fake.cuda.get_device_name = lambda _i: "Tesla T4"
    monkeypatch.setattr(checks, "_import_torch", lambda: fake)
    result = checks.check_device_index(WorkerConfig(qwen_device="cuda:0"))
    assert result.ok is True


def test_device_index_out_of_range_fails(monkeypatch):
    fake = _fake_torch()
    fake.cuda.device_count = lambda: 1
    monkeypatch.setattr(checks, "_import_torch", lambda: fake)
    result = checks.check_device_index(WorkerConfig(qwen_device="cuda:3"))
    assert result.ok is False
    assert "only 1 CUDA device" in result.message


def test_device_index_malformed_fails(monkeypatch):
    fake = _fake_torch()
    fake.cuda.device_count = lambda: 1
    monkeypatch.setattr(checks, "_import_torch", lambda: fake)
    result = checks.check_device_index(WorkerConfig(qwen_device="cuda"))
    assert result.ok is False


def test_qwen_missing_fails(monkeypatch):
    monkeypatch.setattr(checks, "_import_qwen", _fail("qwen_tts"))
    result = checks.check_qwen_installed()
    assert result.ok is False
    assert "qwen-tts==0.1.1" in result.message


def test_qwen_version_mismatch_fails(monkeypatch):
    qwen, _ = _fake_qwen(version="9.9.9")
    monkeypatch.setattr(checks, "_import_qwen", lambda: (qwen, _))
    result = checks.check_qwen_installed()
    assert result.ok is False
    assert "9.9.9" in result.message
    assert "0.1.1" in result.message


def test_qwen_pinned_version_passes(monkeypatch):
    qwen, _ = _fake_qwen(version="0.1.1")
    monkeypatch.setattr(checks, "_import_qwen", lambda: (qwen, _))
    result = checks.check_qwen_installed()
    assert result.ok is True


def test_api_capabilities_missing_method_fails(monkeypatch):
    _, model = _fake_qwen(model_cls=types.SimpleNamespace(from_pretrained=lambda **k: None))
    monkeypatch.setattr(checks, "_import_qwen", lambda: (types.SimpleNamespace(__version__="0.1.1"), model))
    result = checks.check_api_capabilities()
    assert result.ok is False
    assert "generate_voice_clone" in result.message


def test_api_capabilities_complete_passes(monkeypatch):
    qwen, model = _fake_qwen()
    monkeypatch.setattr(checks, "_import_qwen", lambda: (qwen, model))
    result = checks.check_api_capabilities()
    assert result.ok is True


def test_dtype_valid_floating_point(monkeypatch):
    fake = _fake_torch()
    fake.bfloat16 = types.SimpleNamespace(is_floating_point=True)
    monkeypatch.setattr(checks, "_import_torch", lambda: fake)
    result = checks.check_dtype(WorkerConfig(qwen_dtype="bfloat16"))
    assert result.ok is True


def test_dtype_unknown_fails(monkeypatch):
    fake = _fake_torch()
    monkeypatch.setattr(checks, "_import_torch", lambda: fake)
    result = checks.check_dtype(WorkerConfig(qwen_dtype="float128"))
    assert result.ok is False
    assert "not a torch dtype" in result.message


def test_dtype_non_float_fails(monkeypatch):
    fake = _fake_torch()
    fake.int64 = types.SimpleNamespace(is_floating_point=False)
    monkeypatch.setattr(checks, "_import_torch", lambda: fake)
    result = checks.check_dtype(WorkerConfig(qwen_dtype="int64"))
    assert result.ok is False
    assert "not a floating-point dtype" in result.message


def test_run_startup_checks_aborts_when_torch_missing(monkeypatch):
    monkeypatch.setattr(checks, "_import_torch", _fail("torch"))
    monkeypatch.setattr(checks, "_import_qwen", _fail("qwen_tts"))
    results = checks.run_startup_checks(WorkerConfig(backend="qwen"))
    failed = [r for r in results if not r.ok]
    assert failed
    with pytest.raises(checks.StartupError):
        checks.require_ok(results)


def test_run_startup_checks_all_green(monkeypatch):
    torch_fake = _fake_torch(__version__="2.11.0")
    torch_fake.cuda.is_available = lambda: True
    torch_fake.cuda.get_device_name = lambda _i: "Tesla T4"
    torch_fake.cuda.device_count = lambda: 1
    torch_fake.bfloat16 = types.SimpleNamespace(is_floating_point=True)
    monkeypatch.setattr(checks, "_import_torch", lambda: torch_fake)
    qwen, model = _fake_qwen()
    monkeypatch.setattr(checks, "_import_qwen", lambda: (qwen, model))

    results = checks.run_startup_checks(WorkerConfig(backend="qwen"))
    assert all(r.ok for r in results)
    checks.require_ok(results)  # should not raise
