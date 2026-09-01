"""Authenticated audio file streaming (playback, WAV download, exports)."""
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audio, storage
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Narration, User, Voice

router = APIRouter(prefix="/api/files", tags=["files"])
settings = get_settings()

# Phase 5B: multi-format export endpoint (/api/audio/{id}/download?format=).
audio_export_router = APIRouter(prefix="/api/audio", tags=["files"])


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


@audio_export_router.get("/{narration_id}/download")
def download_narration_audio(
    narration_id: str,
    format: str = "wav",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 5B multi-format download: wav (default) or mp3.

    Serves the finished narration converted on the fly. WAV is streamed
    byte-identical from the stored artifact; MP3 conversions are produced
    with ffmpeg and cached under the narration's exports/ directory.
    """
    fmt = (format or "wav").lower().strip().lstrip(".")
    if fmt not in audio.EXPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported export format. Use wav or mp3.",
        )

    narration = db.execute(
        select(Narration).where(
            Narration.id == narration_id, Narration.owner_id == user.id
        )
    ).scalar_one_or_none()
    if narration is None:
        raise HTTPException(status_code=404, detail="Narration not found.")
    if narration.status != "ready" or not narration.final_audio_path:
        raise HTTPException(status_code=409, detail="Audio is not ready.")
    source = storage.safe_resolve(narration.final_audio_path)
    if source is None or not source.is_file():
        raise HTTPException(status_code=404, detail="Audio not found.")

    ext = audio.EXPORT_FORMATS[fmt]["ext"]
    mime = audio.EXPORT_FORMATS[fmt]["mime"]
    filename = f"{narration.title or 'narration'}.{ext}"

    if fmt == "wav":
        data = source.read_bytes()
    else:
        # Cached conversion first; otherwise convert via ffmpeg and persist
        # the result so repeat downloads of the same format are instant.
        cache_rel = storage.narration_export_rel(narration_id, ext)
        cache_path = storage.safe_resolve(cache_rel)
        if cache_path is None or not cache_path.is_file():
            with tempfile.TemporaryDirectory() as td:
                staged = Path(td) / f"audio.{ext}"
                converted = audio.convert_wav_to_format(source, staged, fmt)
                if converted is None:
                    raise HTTPException(
                        status_code=503,
                        detail=f"{fmt.upper()} export is unavailable: ffmpeg is not installed on the server.",
                    )
                export_abs = storage.root() / cache_rel
                export_abs.parent.mkdir(parents=True, exist_ok=True)
                data = converted.read_bytes()
                export_abs.write_bytes(data)
        else:
            data = cache_path.read_bytes()

    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )
