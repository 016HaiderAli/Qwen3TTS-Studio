"""Pydantic request/response schemas."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------- Auth ----------
class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str


# ---------- Voices ----------
class VoiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    language: str = Field(default="English", max_length=50)
    description: str = Field(default="", max_length=2000)
    reference_text: str = Field(default="", max_length=2000)


class VoiceDesignRequest(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    reference_text: str = Field(min_length=1, max_length=2000)
    language: str = Field(default="English", max_length=50)


class VoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    language: str
    description: str
    reference_text: str
    status: str
    has_approved_prompt: bool
    created_at: datetime
    updated_at: datetime


# ---------- Narrations ----------
class NarrationCreate(BaseModel):
    voice_id: str = Field(min_length=1)
    title: str = Field(default="", max_length=300)
    script: str = Field(min_length=1)
    delivery_direction: str = Field(default="", max_length=2000)
    language: str = Field(default="English", max_length=50)


class NarrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    voice_id: str
    title: str
    script: str
    delivery_direction: str
    language: str
    status: str
    chunk_count: int = 0
    chunks_done: int = 0
    duration_sec: float | None = None
    sample_rate: int | None = None
    error: str | None = None
    created_at: datetime


class NarrationListResponse(BaseModel):
    id: str
    title: str
    voice_id: str
    voice_name: str
    status: str
    duration_sec: float | None
    created_at: datetime


# ---------- Jobs ----------
class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    status: str
    voice_id: str | None = None
    narration_id: str | None = None
    progress: int
    attempts: int
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class JobStatusResponse(BaseModel):
    job: JobResponse
    narration: NarrationResponse | None = None
    chunk_total: int = 0
    chunk_done: int = 0


class ErrorResponse(BaseModel):
    detail: str


# ---------- Internal worker API ----------
class JobClaim(BaseModel):
    job_id: str
    type: str
    payload: dict[str, Any]


class ArtifactUploadResponse(BaseModel):
    field: str
    stored: bool


class CompleteRequest(BaseModel):
    sample_rate: int | None = None
    durations: list[float] = []
    notes: dict[str, Any] = {}


class FailRequest(BaseModel):
    error: str = Field(min_length=1, max_length=4000)
