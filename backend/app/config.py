"""Application configuration loaded from environment variables."""
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Core ---
    app_name: str = "Voice Studio"
    debug: bool = False

    # --- HTTP ---
    frontend_url: str = "http://localhost:5173"
    # Redirect URI registered with Google must match this exactly (plus the
    # configured proxy path in dev: the browser path is /auth/callback).
    google_redirect_uri: str = ""

    # --- Database ---
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'voice_studio.db'}"

    # --- Storage ---
    storage_dir: str = str(BASE_DIR / "storage")

    # --- Sessions ---
    session_cookie_name: str = "vs_session"
    session_ttl_seconds: int = 60 * 60 * 24 * 7  # 7 days
    cookie_secure: bool = False  # set True behind HTTPS

    # --- Auth ---
    google_client_id: str = ""
    google_client_secret: str = ""
    google_auth_uri: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_token_uri: str = "https://oauth2.googleapis.com/token"
    google_userinfo_uri: str = "https://openidconnect.googleapis.com/v1/userinfo"
    google_scopes: str = "openid email profile"

    # Disable OAuth and enable /auth/dev-login. NEVER enable in production.
    dev_login: bool = False

    # --- Worker ---
    worker_token: str = ""
    worker_poll_timeout_seconds: int = 30
    max_job_attempts: int = 2
    # Capability every web-tier job is tagged with at enqueue time. "qwen"
    # (default) means only the real Qwen worker can claim it; set to "mock" to
    # run the whole stack intentionally against the mock worker (dev/tests).
    default_job_backend: str = "qwen"
    # Stale-job lease. A job that stays "running" for longer than this without
    # the worker reporting completion/failure is recovered on the next poll:
    # requeued for another attempt if attempts remain, or failed terminally if
    # max_job_attempts are exhausted. The worker processes one job at a time and
    # reports on every request it makes, so a healthy worker refreshes progress
    # far more often than this; 30 minutes comfortably exceeds a typical
    # design/clone/narration job while still detecting a dead worker within a
    # reasonable window. Longer-running deployments should raise it.
    job_lease_seconds: int = 1800

    # --- Limits / validation ---
    max_script_chars: int = 100_000
    max_description_chars: int = 2000
    max_reference_text_chars: int = 2000
    max_delivery_direction_chars: int = 2000
    max_chunk_words: int = 80
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MiB
    supported_languages: list[str] = [
        "Chinese",
        "English",
        "Japanese",
        "Korean",
        "German",
        "French",
        "Russian",
        "Portuguese",
        "Spanish",
        "Italian",
    ]

    # --- CORS ---
    cors_origins: str = ""  # comma-separated extra origins (empty = same-origin only)


    @property
    def resolved_redirect_uri(self) -> str:
        if self.google_redirect_uri:
            return self.google_redirect_uri
        return f"{self.frontend_url.rstrip('/')}/auth/callback"

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir)

    @property
    def origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _apply_dev_worker_token(self) -> "Settings":
        """Dev-only default shared secret, matching start.sh's dev-worker-token.

        Active only when the explicit test-only DEV_LOGIN flag is on; production
        (DEV_LOGIN off) still requires a real WORKER_TOKEN and fails closed.
        """
        if not self.worker_token and self.dev_login:
            self.worker_token = "dev-worker-token"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
