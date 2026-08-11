"""Worker configuration from environment variables."""
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    import os

    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class WorkerConfig:
    backend_url: str = "http://localhost:8000"
    worker_token: str = ""
    # backend selection: "mock" | "qwen"
    backend: str = "mock"
    poll_interval_seconds: float = 2.0
    request_timeout_seconds: float = 120.0

    # mock backend
    mock_sample_rate: int = 24000

    # qwen backend (real GPU worker)
    qwen_model_design: str = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    qwen_model_base: str = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    qwen_device: str = "cuda:0"
    qwen_dtype: str = "bfloat16"
    qwen_keep_design_loaded: bool = False

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        import os

        return cls(
            backend_url=os.environ.get("BACKEND_URL", "http://localhost:8000"),
            worker_token=os.environ.get("WORKER_TOKEN", ""),
            backend=os.environ.get("WORKER_BACKEND", "mock").strip().lower(),
            poll_interval_seconds=float(os.environ.get("POLL_INTERVAL_SECONDS", "2.0")),
            request_timeout_seconds=float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "120.0")),
            mock_sample_rate=int(os.environ.get("MOCK_SAMPLE_RATE", "24000")),
            qwen_model_design=os.environ.get(
                "QWEN_MODEL_DESIGN", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
            ),
            qwen_model_base=os.environ.get(
                "QWEN_MODEL_BASE", "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
            ),
            qwen_device=os.environ.get("QWEN_DEVICE", "cuda:0"),
            qwen_dtype=os.environ.get("QWEN_DTYPE", "bfloat16"),
            qwen_keep_design_loaded=_env_bool("QWEN_KEEP_DESIGN_LOADED", False),
        )

    @property
    def requires_gpu(self) -> bool:
        return self.backend == "qwen"
