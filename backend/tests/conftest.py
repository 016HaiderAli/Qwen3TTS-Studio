"""Pytest fixtures.

Environment is configured BEFORE importing the app so the module-level
``engine`` and cached settings point at a disposable temp database and storage
root. No production data is touched.
"""
import importlib
import os
import sys
import tempfile
from pathlib import Path

# --- set test env before importing the app ----------------------------------
_TMP = Path(tempfile.mkdtemp(prefix="voice-studio-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["STORAGE_DIR"] = str(_TMP / "storage")
os.environ["WORKER_TOKEN"] = "test-worker-token"
os.environ["DEV_LOGIN"] = "1"
os.environ["COOKIE_SECURE"] = "0"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "http://testserver/auth/callback"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "worker"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import models  # noqa: E402,F401
from app.config import get_settings  # noqa: E402
from app.db import Base, engine, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    init_db()
    yield


@pytest.fixture(autouse=True)
def _clean_db():
    """Truncate all tables before each test (FK-aware order)."""
    yield
    with engine.begin() as conn:
        for table in (
            "jobs",
            "narrations",
            "voices",
            "sessions",
            "users",
        ):
            conn.execute(text(f"DELETE FROM {table}"))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def settings():
    return get_settings()


# ---------- helpers ----------
@pytest.fixture
def dev_login(client):
    def _login(email: str = "alice@example.com") -> str:
        resp = client.get(f"/auth/dev-login?email={email}")
        assert resp.status_code == 200, resp.text
        return client.cookies.get(settings_session_cookie())

    return _login


def settings_session_cookie() -> str:
    return get_settings().session_cookie_name


@pytest.fixture
def make_wav_bytes():
    """Build a valid mono PCM16 WAV in memory."""
    import io
    import wave

    def _make(sr: int = 24000, seconds: float = 1.0) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(b"\x00\x00" * int(sr * seconds))
        return buf.getvalue()

    return _make
