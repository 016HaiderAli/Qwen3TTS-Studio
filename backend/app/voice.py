"""System-level voice records that are not user-owned.

Built-in narrations (Qwen CustomVoice speakers) are not tied to a user voice
record, but the ``narrations`` table requires a non-NULL ``voice_id`` for FK
integrity. A single system-owned voice record acts as a placeholder so built-in
narrations can reference a valid voice row without changing the DB schema.
"""
from __future__ import annotations

from sqlalchemy import insert, select, text

from .db import engine
from .models import User, Voice

BUILTIN_VOICE_ID = "00000000-0000-0000-0000-000000000000"
BUILTIN_VOICE_NAME = "__builtin_voices__"


def ensure_builtin_voice() -> None:
    """Create the system user and system voice record if they do not already exist.

    Safe to call multiple times. Uses ``INSERT OR IGNORE`` so it is idempotent
    even when called from tests with a fresh temp database.
    """
    with engine.begin() as conn:
        # Upsert user (INSERT OR IGNORE — skip if already exists).
        conn.execute(
            insert(User).prefix_with("OR IGNORE").values(
                id=BUILTIN_VOICE_ID,
                google_sub=BUILTIN_VOICE_ID,
                email="",
                name="",
            )
        )
        # Upsert voice (INSERT OR IGNORE — skip if already exists).
        conn.execute(
            insert(Voice).prefix_with("OR IGNORE").values(
                id=BUILTIN_VOICE_ID,
                owner_id=BUILTIN_VOICE_ID,
                name=BUILTIN_VOICE_NAME,
                language="English",
                description="System placeholder for built-in Qwen CustomVoice narrations.",
                reference_text="",
                status="approved",
                reference_audio_path=None,
                prompt_pt_path=None,
            )
        )


def get_builtin_voice_id() -> str:
    """Return the built-in system voice id, creating records if they do not exist.

    Idempotent and safe to call from tests where the startup event may not have
    fired against the current database.
    """
    ensure_builtin_voice()
    return BUILTIN_VOICE_ID
