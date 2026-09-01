"""Pydantic request/response schemas."""
from datetime import datetime
from enum import Enum
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


class VoiceCloneResponse(BaseModel):
    """Phase 7A: response of the upload-and-clone voice endpoint."""

    id: str
    display_name: str
    reference_url: str


# ---------- Narrations ----------
class EmotionPreset(str, Enum):
    neutral = "neutral"
    happy = "happy"
    sad = "sad"
    angry = "angry"
    calm = "calm"
    fierce = "fierce"
    whisper = "whisper"


class VoiceSetting(BaseModel):
    """Alibaba Model Studio voice parameters (Phase 7B).

    Mirrors the model-studio ``voice_setting`` structure so the job payload and
    the frontend controls speak one vocabulary: ``speed`` (0.5x-2.0x), ``pitch``
    (semitone shift, -12..+12), ``vol`` (gain, 0.5x-1.5x) and an ``emotion``
    preset. ``voice_id`` is the built-in speaker id or approved custom voice id.
    """

    voice_id: str = Field(default="", max_length=200)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    pitch: int = Field(default=0, ge=-12, le=12)
    vol: float = Field(default=1.0, ge=0.5, le=1.5)
    emotion: EmotionPreset = EmotionPreset.neutral


class NarrationCreate(BaseModel):
    voice_id: str = Field(min_length=1)
    title: str = Field(default="", max_length=300)
    script: str = Field(min_length=1)
    delivery_direction: str = Field(default="", max_length=2000)
    delivery_instruction: str = Field(default="", max_length=2000)
    language: str = Field(default="English", max_length=50)
    voice_setting: VoiceSetting | None = None


class NarrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    voice_id: str | None = None
    title: str
    script: str
    delivery_direction: str
    language: str
    status: str
    # "voice_clone" for user-approved voices, "custom_voice" for built-in
    # Qwen speakers, None for jobs that have not been classified yet. The
    # value is derived from the most recent Job row for the narration; a
    # narration created via /api/builtin-voices/generate has voice_id NULL
    # and voice_source="custom_voice".
    voice_source: str | None = None
    # Number of distinct speakers in the narration. 1 = single-speaker.
    # Used by the frontend to show a Multi-Speaker badge and render dialogue
    # segment details.
    dialogue_speaker_count: int = 1
    # List of dialogue segments with speaker/text pairs, present only for
    # multi-speaker narrations. Derived from the job payload at serve time.
    dialogue_segments: list[dict] = []
    chunk_count: int = 0
    chunks_done: int = 0
    duration_sec: float | None = None
    sample_rate: int | None = None
    error: str | None = None
    created_at: datetime


class NarrationListResponse(BaseModel):
    id: str
    title: str
    voice_id: str | None = None
    voice_name: str | None = None
    voice_source: str | None = None
    dialogue_speaker_count: int = 1
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
    required_backend: str
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


# ---------- Built-in voices (Qwen CustomVoice) ----------
class BuiltinVoiceInfo(BaseModel):
    id: str
    description: str
    native_language: str


class DialogueSegmentPayload(BaseModel):
    speaker: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=10_000)
    instruct: str = Field(default="", max_length=500)


class BuiltinVoiceGenerateRequest(BaseModel):
    speaker: str = Field(min_length=1, max_length=64)
    language: str = Field(default="English", max_length=50)
    script: str = Field(default="")
    # Natural-language delivery direction. Optional for CustomVoice (the
    # model's `instruct` parameter); an empty string is forwarded as
    # ``instruct=None`` to the model.
    instruct: str = Field(default="", max_length=2_000)
    # Phase 7B alias matching the Alibaba model-studio payload vocabulary.
    # ``delivery_instruction`` and ``voice_setting`` mirror the request bodies
    # used by the model-studio APIs; ``instruct``/``delivery_direction`` are
    # kept as the legacy spelling for the same values.
    delivery_instruction: str = Field(default="", max_length=2_000)
    voice_setting: VoiceSetting | None = None
    title: str = Field(default="", max_length=300)
    # Multi-speaker dialogue segments. When provided, ``script`` is ignored and
    # the job processes each segment independently (per-speaker TTS generation).
    dialogue_segments: list[DialogueSegmentPayload] | None = Field(
        default=None, max_length=50
    )


# ---------- Internal worker API ----------
class JobClaim(BaseModel):
    job_id: str
    type: str
    payload: dict[str, Any]
    # Opaque ownership token minted at claim time. The worker must present it
    # (X-Job-Claim-Token) on every artifact/complete/fail call for this job.
    claim_token: str


class ArtifactUploadResponse(BaseModel):
    field: str
    stored: bool


class CompleteRequest(BaseModel):
    sample_rate: int | None = None
    durations: list[float] = []
    notes: dict[str, Any] = {}


class FailRequest(BaseModel):
    error: str = Field(min_length=1, max_length=4000)
