"""Local filesystem storage for artifacts (reference WAV, .pt prompts, audio).

Implements the local-storage layout from docs/MVP_ARCHITECTURE.md section 6.4.
Paths stored in the database are always relative to the storage root and are
validated on resolution to prevent path traversal.
"""
from pathlib import Path

from .config import get_settings


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


def voice_prompt_rel(voice_id: str) -> str:
    return f"voices/{voice_id}/voice_clone_prompt.pt"


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
    target = _root() / f"voices/{voice_id}"
    if target.exists():
        import shutil

        shutil.rmtree(target, ignore_errors=True)


def remove_narration_artifacts(narration_id: str) -> None:
    target = _root() / f"narrations/{narration_id}"
    if target.exists():
        import shutil

        shutil.rmtree(target, ignore_errors=True)
