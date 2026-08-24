"""Local filesystem storage for artifacts (reference WAV, .pt prompts, audio).

Implements the local-storage layout from docs/MVP_ARCHITECTURE.md section 6.4.
Paths stored in the database are always relative to the storage root and are
validated on resolution to prevent path traversal.
"""
import logging
import os
import shutil
from pathlib import Path

from .config import get_settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    pass


def _root() -> Path:
    return get_settings().storage_path


def root() -> Path:
    return _root()


def safe_resolve(rel_path: str | None) -> Path | None:
    """Resolve a DB-stored relative path to a real file, rejecting traversal.

    Returns None for empty input. Raises StorageError if the relative path
    escapes the storage root or references a non-file.
    """
    if not rel_path:
        return None
    p = Path(rel_path)
    if p.is_absolute() or ".." in p.parts:
        raise StorageError("invalid storage path")
    root = _root().resolve()
    candidate = (root / p).resolve()
    if root not in candidate.parents and candidate != root:
        raise StorageError("path escapes storage root")
    if not candidate.is_file():
        return None
    return candidate


def write_bytes(rel_path: str, data: bytes) -> str:
    p = Path(rel_path)
    if p.is_absolute() or ".." in p.parts:
        raise StorageError("invalid storage path")
    target = _root() / p
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return rel_path


def read_bytes(rel_path: str) -> bytes:
    target = safe_resolve(rel_path)
    if target is None:
        raise FileNotFoundError(rel_path)
    return target.read_bytes()


def ensure_layout() -> None:
    root = _root()
    (root / "voices").mkdir(parents=True, exist_ok=True)
    (root / "narrations").mkdir(parents=True, exist_ok=True)


def voice_reference_rel(voice_id: str) -> str:
    return f"voices/{voice_id}/reference.wav"


def voice_preview_rel(voice_id: str) -> str:
    return f"voices/{voice_id}/preview.wav"


def promote_preview_to_reference(voice_id: str) -> str:
    """Make the current draft preview the voice's live reference.

    Called when an approval is initiated: the preview the user approved becomes
    the reference audio the new clone prompt is built from. If no draft preview
    exists (e.g. an approval retry after a failed clone), the previously
    promoted reference is already the live one and is left in place.

    Returns the relative reference path.
    """
    preview = _root() / voice_preview_rel(voice_id)
    live = _root() / voice_reference_rel(voice_id)
    live.parent.mkdir(parents=True, exist_ok=True)
    if preview.exists():
        os.replace(preview, live)
    elif not live.exists():
        raise FileNotFoundError(voice_preview_rel(voice_id))
    return voice_reference_rel(voice_id)


def voice_prompt_rel(voice_id: str) -> str:
    return f"voices/{voice_id}/voice_clone_prompt.pt"


def voice_prompt_staged_rel(voice_id: str) -> str:
    return f"voices/{voice_id}/voice_clone_prompt.staged.pt"


def promote_voice_prompt(voice_id: str) -> str:
    """Promote the staged clone prompt to the live prompt path.

    Called when a clone_prompt job completes successfully: the .pt uploaded by
    the worker lives at a staged path until then, so a failed or retried job
    can never overwrite a previously approved prompt at the referenced path.
    The staged file is moved into the live slot atomically via os.replace.

    Returns the relative live prompt path.
    """
    staged = _root() / voice_prompt_staged_rel(voice_id)
    live = _root() / voice_prompt_rel(voice_id)
    live.parent.mkdir(parents=True, exist_ok=True)
    if not staged.exists():
        raise FileNotFoundError(voice_prompt_staged_rel(voice_id))
    os.replace(staged, live)
    return voice_prompt_rel(voice_id)


def remove_staged_voice_prompt(voice_id: str) -> None:
    """Remove a clone job's staged prompt file.

    Called when a clone_prompt job fails or is requeued: the staged .pt from
    the attempt is partial/unverified and must not survive, while any previously
    approved live prompt is preserved. Best-effort: a failure here is logged but
    never propagated.
    """
    target = _root() / voice_prompt_staged_rel(voice_id)
    if target.exists():
        try:
            target.unlink()
        except OSError as exc:
            logger.warning(
                "failed to remove staged voice prompt for %s: %s", voice_id, exc
            )


def narration_chunk_rel(narration_id: str, index: int) -> str:
    return f"narrations/{narration_id}/chunks/chunk_{index:03d}.wav"


def narration_final_rel(narration_id: str) -> str:
    return f"narrations/{narration_id}/final.wav"


def narration_chunk_dir(narration_id: str) -> Path:
    return _root() / f"narrations/{narration_id}/chunks"


def narration_chunk_paths(narration_id: str, count: int) -> list[Path]:
    return [
        _root() / narration_chunk_rel(narration_id, i) for i in range(count)
    ]


def remove_voice_artifacts(voice_id: str) -> None:
    """Remove the voice's filesystem artifacts.

    Called only after the owning DB row has been committed; a failure here is
    logged but never propagated, so an already-committed deletion is never
    rolled back.
    """
    target = _root() / f"voices/{voice_id}"
    if target.exists():
        try:
            shutil.rmtree(target)
        except OSError as exc:
            logger.warning(
                "failed to remove voice artifacts for %s: %s", voice_id, exc
            )


def remove_narration_artifacts(narration_id: str) -> None:
    """Remove a narration's filesystem artifacts (chunks + final audio).

    Called only after the owning DB row has been committed; a failure here is
    logged but never propagated, so an already-committed deletion is never
    rolled back.
    """
    target = _root() / f"narrations/{narration_id}"
    if target.exists():
        try:
            shutil.rmtree(target)
        except OSError as exc:
            logger.warning(
                "failed to remove narration artifacts for %s: %s",
                narration_id,
                exc,
            )


def remove_voice_preview(voice_id: str) -> None:
    """Remove the voice's draft preview file.

    Called when a design job fails terminally: the draft preview from the
    failed attempt is stale (an approved voice is served from its reference,
    and a draft voice has no preview to approve), so it is removed best-effort.
    A failure here is logged but never propagated.
    """
    target = _root() / voice_preview_rel(voice_id)
    if target.exists():
        try:
            target.unlink()
        except OSError as exc:
            logger.warning(
                "failed to remove voice preview for %s: %s", voice_id, exc
            )
