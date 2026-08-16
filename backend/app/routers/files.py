"""Authenticated audio file streaming (playback and WAV download)."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import storage
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Narration, User, Voice

router = APIRouter(prefix="/api/files", tags=["files"])
settings = get_settings()


def _stream(path, filename: str, download: bool):
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Audio not found.")
    data = path.read_bytes()
    disposition = "attachment" if download else "inline"
    return Response(
        content=data,
        media_type="audio/wav",
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


def _reference_audio(voice: Voice) -> Path | None:
    """Choose the audio to stream for a voice.

    - approved: the live reference (the preview that was promoted on approval).
    - preview_ready: the current draft preview candidate; falls back to the
      live reference when a promotion already happened (e.g. approval retry).
    - designing/approving: keep the saved approved reference streamable while a
      redesign runs, so the voice stays usable; otherwise the draft preview.
    """
    if voice.status == "approved":
        return storage.safe_resolve(voice.reference_audio_path)
    if voice.status == "preview_ready":
        preview = storage.safe_resolve(storage.voice_preview_rel(voice.id))
        if preview is not None:
            return preview
        return storage.safe_resolve(voice.reference_audio_path)
    if voice.status in ("designing", "approving"):
        if voice.reference_audio_path:
            saved = storage.safe_resolve(voice.reference_audio_path)
            if saved is not None:
                return saved
        return storage.safe_resolve(storage.voice_preview_rel(voice.id))
    return None


@router.get("/voices/{voice_id}/reference")
def voice_reference(
    voice_id: str,
    download: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    voice = db.execute(
        select(Voice).where(Voice.id == voice_id, Voice.owner_id == user.id)
    ).scalar_one_or_none()
    if voice is None:
        raise HTTPException(status_code=404, detail="Voice not found.")
    path = _reference_audio(voice)
    return _stream(path, f"{voice.name}-reference.wav", download)


@router.get("/narrations/{narration_id}/audio")
def narration_audio(
    narration_id: str,
    download: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    narration = db.execute(
        select(Narration).where(
            Narration.id == narration_id, Narration.owner_id == user.id
        )
    ).scalar_one_or_none()
    if narration is None:
        raise HTTPException(status_code=404, detail="Narration not found.")
    if narration.status != "ready" or not narration.final_audio_path:
        raise HTTPException(status_code=409, detail="Audio is not ready.")
    path = storage.safe_resolve(narration.final_audio_path)
    filename = f"{narration.title or 'narration'}.wav"
    return _stream(path, filename, download)
