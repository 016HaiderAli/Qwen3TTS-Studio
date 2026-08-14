"""SQLAlchemy ORM models.

Mirrors the MVP schema from docs/MVP_ARCHITECTURE.md section 3.2.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    google_sub: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    voices: Mapped[list["Voice"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    narrations: Mapped[list["Narration"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    user: Mapped["User"] = relationship(back_populates="sessions")


class Voice(Base):
    __tablename__ = "voices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(50), default="English")
    description: Mapped[str] = mapped_column(Text, default="")
    reference_text: Mapped[str] = mapped_column(Text, default="")
    # draft | designing | preview_ready | approving | approved
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    reference_audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_pt_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    owner: Mapped["User"] = relationship(back_populates="voices")
    narrations: Mapped[list["Narration"]] = relationship(
        back_populates="voice", cascade="all, delete-orphan"
    )


class Narration(Base):
    __tablename__ = "narrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    voice_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("voices.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="")
    script: Mapped[str] = mapped_column(Text)
    delivery_direction: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(50), default="English")
    # ready | queued | running | failed
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    chunks_json: Mapped[str] = mapped_column(Text, default="[]")
    chunk_durations_json: Mapped[str] = mapped_column(Text, default="[]")
    final_audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    owner: Mapped["User"] = relationship(back_populates="narrations")
    voice: Mapped["Voice"] = relationship(back_populates="narrations")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # design | clone_prompt | narration
    type: Mapped[str] = mapped_column(String(30), index=True)
    # worker capability required to claim this job: "qwen" | "mock".
    # A mock worker can never claim a job tagged for the real qwen worker.
    required_backend: Mapped[str] = mapped_column(String(30), default="qwen", index=True)
    # queued | running | succeeded | failed
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    voice_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("voices.id", ondelete="CASCADE"), nullable=True
    )
    narration_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("narrations.id", ondelete="CASCADE"), nullable=True
    )
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
