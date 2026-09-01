"""Public preview-audio endpoints for built-in Qwen speakers.

The static ``backend/app/static/previews/`` directory ships with one WAV per
known built-in speaker (lower-case id → ``{clean_id}.wav`` on disk; a
case-insensitive scan covers file systems that store the canonical mixed
case). These are served through ``GET /api/voices/{speaker_id}/preview``
with ``Content-Disposition: inline`` and ``Accept-Ranges: bytes`` so the
frontend's ArrayBuffer-decoding preview path never triggers browser download
managers (IDM, etc.) and never has to deal with range-not-satisfied errors.
"""
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

# ``backend/app/`` — robust regardless of where uvicorn is launched from.
_APP_DIR = Path(__file__).resolve().parent.parent
PREVIEWS_DIR = _APP_DIR / "static" / "previews"

# Canonical file names on disk (may be mixed case; lookup is case-insensitive).
BUILTIN_PREVIEW_FILES: dict[str, str] = {
    "vivian": "Vivian.wav",
    "serena": "Serena.wav",
    "uncle_fu": "Uncle_Fu.wav",
    "dylan": "Dylan.wav",
    "eric": "Eric.wav",
    "ryan": "Ryan.wav",
    "aiden": "Aiden.wav",
    "ono_anna": "Ono_Anna.wav",
    "sohee": "Sohee.wav",
}

router = APIRouter(prefix="/api/voices", tags=["voices"])


def normalize_speaker_id(speaker_id: str) -> str:
    """Canonicalize a speaker id for case-insensitive lookup."""
    return speaker_id.lower().replace(" ", "_")


def _resolve_preview_file(clean_id: str) -> Path | None:
    """Locate ``previews/{clean_id}.wav`` case-insensitively.

    ``{clean_id}.wav`` is the on-disk name as authored (canonical speakers
    keep mixed case like ``Uncle_Fu.wav``), so an exact match is tried first
    and a directory scan covers case-sensitive file systems (Linux/macOS CI)
    versus case-insensitive ones (Windows dev).
    """
    if not PREVIEWS_DIR.is_dir():
        logger.warning("preview directory missing entirely: %s", PREVIEWS_DIR)
        return None

    exact = PREVIEWS_DIR / f"{clean_id}.wav"
    logger.info("Looking for preview at path: %s", exact)
    if exact.is_file():
        return exact

    target_name = f"{clean_id}.wav".lower()
    for candidate in sorted(PREVIEWS_DIR.iterdir()):
        if candidate.name.lower() == target_name and candidate.is_file():
            logger.info(
                "Preview found via case-insensitive fallback: %s (for %s)",
                candidate,
                clean_id,
            )
            return candidate
    return None


def _is_known_speaker(clean_id: str) -> bool:
    return clean_id in BUILTIN_PREVIEW_FILES or (PREVIEWS_DIR / f"{clean_id}.wav").exists()


@router.get("/{speaker_id}/preview", include_in_schema=False)
def builtin_voice_preview(speaker_id: str):
    """Stream a built-in speaker's preview WAV.

    Public (no auth dependency) so the VoiceSelector can preview voices for
    visitors who haven't signed in yet. The ``inline`` Content-Disposition
    keeps IDM and similar download managers from prompting a save dialog.

    Speaker ids are normalized (``clean_id = speaker_id.lower().replace(" ",
    "_")``) so ``Vivian``, ``vivian``, ``Uncle Fu`` and ``UNCLE_FU`` all
    resolve. Returns 404 for unknown speakers and — with an on-disk diagnostic
    detail — when the WAV is missing despite a known speaker.
    """
    clean_id = normalize_speaker_id(speaker_id)
    if not clean_id.isidentifier():
        raise HTTPException(status_code=404, detail="Preview not available for this speaker.")

    path = _resolve_preview_file(clean_id)
    if path is None:
        if _is_known_speaker(clean_id):
            raise HTTPException(
                status_code=404, detail=f"Preview file for {clean_id} not found on disk"
            )
        raise HTTPException(status_code=404, detail="Preview not available for this speaker.")

    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Content-Disposition": 'inline; filename="preview.wav"'},
    )
