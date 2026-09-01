"""Phase 7A: audio-driven voice cloning from an uploaded reference clip.

``POST /api/voices/clone`` accepts a short browser-audio upload (WAV/MP3/OGG/
M4A), transcodes it to 24 kHz mono PCM16, validates the 2-30 s window,
trims dead lead-in/lead-out silence and normalizes the clip to the Phase 5B
-14 LUFS target, then registers the result as an **approved** custom voice.

The canonical reference copy is stored under
``backend/app/static/custom_voices/{voice_id}/reference.wav`` per the feature
spec; identical working copies land in the voice's storage slots
(``voices/{id}/reference.wav`` served by the existing
``GET /api/files/voices/{id}/reference`` download endpoint, and the draft
preview slot required by the ``clone_prompt`` job contract).

A ``clone_prompt`` job is enqueued so a worker (mock or Qwen) derives the
real clone embedding from the reference; until it lands, the voice is fully
registered and visible in the studio's VoiceSelector.
"""
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from .. import audio, jobs as job_service, storage
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import User, Voice
from ..schemas import VoiceCloneResponse

logger = logging.getLogger(__name__)

# Route paths are defined WITHOUT a prefix here: the prefix is applied exactly
# once at include time in app/main.py (prefix="/api/voices") so the final path
# is unambiguous POST /api/voices/clone — never a duplicated /api/voices/api/voices/….
router = APIRouter(tags=["voice-clone"])
settings = get_settings()

# Canonical clone-reference artifacts required by the Phase 7A spec:
# backend/app/static/custom_voices/{voice_id}/reference.wav
APP_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
CLONE_STATIC_ROOT = APP_STATIC_DIR / "custom_voices"

SUPPORTED_UPLOAD_SUFFIXES = {".wav", ".mp3", ".ogg", ".m4a", ".aac", ".flac", ".webm"}


def clone_static_dir(voice_id: str) -> Path:
    return CLONE_STATIC_ROOT / voice_id


def remove_clone_static_copy(voice_id: str) -> None:
    """Best-effort cleanup of a deleted voice's app-static clone copy."""
    target = clone_static_dir(voice_id)
    try:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("failed to remove clone copy for %s: %s", voice_id, exc)


@router.post("/clone", response_model=VoiceCloneResponse, status_code=status.HTTP_200_OK)
@router.post("/clone/", response_model=VoiceCloneResponse, status_code=status.HTTP_200_OK)
async def clone_voice(
    file: UploadFile = File(...),
    display_name: str = Form(...),
    language: str = Form("English"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = display_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Display name is required.")
    if len(name) > 200:
        raise HTTPException(status_code=422, detail="Display name too long (max 200).")
    if language not in settings.supported_languages:
        raise HTTPException(status_code=422, detail="Unsupported language.")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail="Unsupported file type. Allowed: WAV, MP3, OGG, M4A.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MiB upload limit.",
        )

    voice_id = str(uuid.uuid4())
    staged_dir = clone_static_dir(voice_id)
    final_path = staged_dir / "reference.wav"

    try:
        duration = audio.decode_upload_to_reference_wav(data, suffix, final_path)
    except audio.AudioError as exc:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc))

    if duration < audio.CLONE_MIN_SECONDS:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise HTTPException(
            status_code=422,
            detail=f"Reference clip is {duration:.1f}s; at least {audio.CLONE_MIN_SECONDS:.0f} seconds are required.",
        )
    if duration > audio.CLONE_MAX_SECONDS:
        shutil.rmtree(staged_dir, ignore_errors=True)
        raise HTTPException(
            status_code=422,
            detail=f"Reference clip is {duration:.1f}s; {audio.CLONE_MAX_SECONDS:.0f} seconds maximum.",
        )

    # Trim dead edges + normalize loudness in place, reusing the Phase 5B
    # narration post-processing pipeline (same thresholds as finished audio).
    try:
        audio.postprocess_narration_wav(
            final_path,
            threshold_db=settings.silence_threshold_db,
            target_lufs=settings.loudness_target_lufs,
        )
    except audio.AudioError as exc:
        logger.warning("clone %s: post-processing failed (%s); keeping decoded clip", voice_id, exc)

    processed = final_path.read_bytes()
    # Working copies in the voice's storage slots so every existing consumer
    # (download/preview/reference, clone_prompt payload reader) works unchanged.
    storage.write_bytes(storage.voice_reference_rel(voice_id), processed)
    storage.write_bytes(storage.voice_preview_rel(voice_id), processed)

    voice = Voice(
        id=voice_id,
        owner_id=user.id,
        name=name,
        language=language,
        description="Cloned from a 3-10 s reference sample (upload).",
        reference_text="Voice cloning reference sample.",
        status="approved",
        reference_audio_path=storage.voice_reference_rel(voice_id),
    )
    db.add(voice)
    db.flush()

    # Give the voice a real clone prompt as soon as a worker claims it; the
    # already-approved status and live reference let it show in the studio now.
    job_service.enqueue(
        db,
        owner_id=user.id,
        type_="clone_prompt",
        payload=job_service.clone_prompt_payload(voice),
        voice_id=voice.id,
    )
    db.commit()

    return VoiceCloneResponse(
        id=voice.id,
        display_name=voice.name,
        reference_url=f"/api/files/voices/{voice.id}/reference",
    )
