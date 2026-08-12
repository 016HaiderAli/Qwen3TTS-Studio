"""GPU-worker startup validation for the real Qwen3-TTS backend.

Runs on the CUDA host before the worker starts polling, producing actionable
errors when the environment cannot run qwen-tts (missing torch, no CUDA, no
qwen-tts, incompatible qwen-tts version, bad device/dtype).

Importing this module must NOT import torch or qwen-tts, so the mock path stays
GPU-free. The ``_import_*`` helpers are monkeypatchable in tests.
"""
import importlib.metadata
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("qwen-worker")

# qwen-tts==0.1.1 is the pinned, notebook-installed version (reference/Voice_Studio.ipynb
# cell 7). The worker code and prompt schema are validated against it.
PINNED_QWEN_TTS_VERSION = "0.1.1"

REQUIRED_API_METHODS = (
    "from_pretrained",
    "generate_voice_design",
    "create_voice_clone_prompt",
    "generate_voice_clone",
)


class StartupError(Exception):
    """Raised when one or more startup checks fail."""


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str


def _import_torch():
    import torch

    return torch


def _import_qwen():
    import qwen_tts
    from qwen_tts import Qwen3TTSModel

    return qwen_tts, Qwen3TTSModel


def check_torch_installed() -> CheckResult:
    try:
        torch = _import_torch()
    except ImportError as exc:
        return CheckResult(
            "torch",
            False,
            f"PyTorch is not installed ({exc}). Install "
            "worker/requirements-qwen.txt on the CUDA host.",
        )
    return CheckResult("torch", True, f"PyTorch {torch.__version__}")


def check_cuda_available() -> CheckResult:
    try:
        torch = _import_torch()
    except ImportError as exc:
        return CheckResult("cuda", False, f"skipped (torch not installed): {exc}")
    if not torch.cuda.is_available():
        return CheckResult(
            "cuda",
            False,
            "torch.cuda.is_available() is False. The real qwen backend requires "
            "a CUDA GPU (the notebook runs on an NVIDIA Tesla T4). Install a "
            "CUDA-enabled torch build and confirm with `nvidia-smi`.",
        )
    return CheckResult(
        "cuda", True, f"CUDA available: {torch.cuda.get_device_name(0)}"
    )


def check_device_index(config) -> CheckResult:
    try:
        torch = _import_torch()
    except ImportError as exc:
        return CheckResult("device", False, f"skipped (torch not installed): {exc}")
    match = re.match(r"^cuda:(\d+)$", config.qwen_device)
    if not match:
        return CheckResult(
            "device",
            False,
            f"qwen_device={config.qwen_device!r} must look like cuda:<index> "
            "(e.g. cuda:0). Fix QWEN_DEVICE.",
        )
    index = int(match.group(1))
    count = torch.cuda.device_count()
    if index >= count:
        return CheckResult(
            "device",
            False,
            f"qwen_device={config.qwen_device!r} but only {count} CUDA "
            f"device(s) present; use cuda:0..{max(count - 1, 0)} or fix QWEN_DEVICE.",
        )
    return CheckResult(
        "device",
        True,
        f"device {config.qwen_device} present ({torch.cuda.get_device_name(index)})",
    )


def _qwen_dist_version() -> str | None:
    """Return the installed qwen-tts distribution version, or None.

    The qwen-tts==0.1.1 wheel does not set a usable ``qwen_tts.__version__``
    attribute (its ``__init__.py`` lists ``__version__`` in ``__all__`` without
    assigning it), so the version is read from the installed distribution
    metadata instead.
    """
    try:
        return importlib.metadata.version("qwen-tts")
    except importlib.metadata.PackageNotFoundError:
        return None


def check_qwen_installed() -> CheckResult:
    try:
        _import_qwen()
    except ImportError as exc:
        return CheckResult(
            "qwen-tts",
            False,
            f"qwen-tts is not installed ({exc}). Install "
            "worker/requirements-qwen.txt (pins qwen-tts==0.1.1).",
        )
    version = _qwen_dist_version() or "unknown"
    if version != PINNED_QWEN_TTS_VERSION:
        return CheckResult(
            "qwen-tts",
            False,
            f"qwen-tts {version} is installed, but this worker is validated "
            f"against qwen-tts=={PINNED_QWEN_TTS_VERSION} (pinned in "
            "worker/requirements-qwen.txt per reference/Voice_Studio.ipynb). "
            "Pin qwen-tts==0.1.1 before running.",
        )
    return CheckResult("qwen-tts", True, f"qwen-tts {version}")


def check_api_capabilities() -> CheckResult:
    try:
        _, model_cls = _import_qwen()
    except ImportError as exc:
        return CheckResult("api", False, f"skipped (qwen-tts not installed): {exc}")
    missing = [m for m in REQUIRED_API_METHODS if not callable(getattr(model_cls, m, None))]
    if missing:
        return CheckResult(
            "api",
            False,
            f"Qwen3TTSModel is missing required method(s): {missing}. Expected "
            f"for qwen-tts=={PINNED_QWEN_TTS_VERSION}.",
        )
    return CheckResult(
        "api",
        True,
        "Qwen3TTSModel API surface matches expectations "
        "(from_pretrained, generate_voice_design, create_voice_clone_prompt, "
        "generate_voice_clone)",
    )


def check_dtype(config) -> CheckResult:
    try:
        torch = _import_torch()
    except ImportError as exc:
        return CheckResult("dtype", False, f"skipped (torch not installed): {exc}")
    dtype = getattr(torch, config.qwen_dtype, None)
    if dtype is None:
        return CheckResult(
            "dtype",
            False,
            f"qwen_dtype={config.qwen_dtype!r} is not a torch dtype. Set "
            "QWEN_DTYPE to e.g. bfloat16.",
        )
    if not getattr(dtype, "is_floating_point", False):
        return CheckResult(
            "dtype",
            False,
            f"qwen_dtype={config.qwen_dtype} is not a floating-point dtype; "
            "TTS requires float weights.",
        )
    return CheckResult("dtype", True, f"dtype torch.{config.qwen_dtype}")


def run_startup_checks(config) -> list[CheckResult]:
    """Run all GPU-worker startup checks; callers decide whether to abort."""
    results = [
        check_torch_installed(),
        check_cuda_available(),
        check_device_index(config),
        check_qwen_installed(),
        check_api_capabilities(),
        check_dtype(config),
    ]
    for result in results:
        if result.ok:
            logger.info("startup check %s: %s", result.name, result.message)
        else:
            logger.error("startup check %s FAILED: %s", result.name, result.message)
    return results


def require_ok(results: list[CheckResult]) -> None:
    """Raise StartupError listing every failed check."""
    failed = [r for r in results if not r.ok]
    if failed:
        details = "; ".join(f"{r.name}: {r.message}" for r in failed)
        raise StartupError(f"GPU worker startup failed ({len(failed)} check(s)): {details}")
