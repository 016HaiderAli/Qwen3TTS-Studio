"""Storage maintenance: remove orphaned chunk WAV files and prune stale job records."""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from . import storage
from .db import get_db_context
from .models import Job, Narration

logger = logging.getLogger(__name__)


def sweep_orphaned_chunks() -> int:
    """Remove chunk WAV files for narrations whose final.wav is present.

    After a narration job completes, the final concatenated audio is written to
    narrations/<id>/final.wav.  The individual chunk files (chunk_000.wav,
    chunk_001.wav, …) are no longer needed once the final audio exists and are
    deleted by this function.  Returns the number of chunk directories pruned.
    """
    removed = 0
    root = storage.root()
    narrations_dir = root / "narrations"
    if not narrations_dir.is_dir():
        return 0

    for narration_path in narrations_dir.iterdir():
        if not narration_path.is_dir():
            continue
        chunks_dir = narration_path / "chunks"
        final_file = narration_path / "final.wav"
        if final_file.is_file() and chunks_dir.is_dir():
            try:
                storage.shutil.rmtree(chunks_dir)
                removed += 1
                logger.info("removed chunks dir for narration %s", narration_path.name)
            except OSError as exc:
                logger.warning("failed to remove chunks dir for %s: %s", narration_path.name, exc)

    return removed


def prune_stale_jobs(older_than_hours: int = 24 * 7) -> int:
    """Delete Job rows in a terminal state older than the given threshold.

    Terminal states are: completed, cancelled, failed.
    Returns the number of job rows deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    with get_db_context() as db:
        result = db.execute(
            delete(Job).where(
                Job.status.in_(["completed", "cancelled", "failed"]),
                Job.updated_at < cutoff,
            )
        )
        deleted = result.rowcount
        if deleted:
            logger.info("pruned %d stale job rows", deleted)
        return deleted


def prune_orphaned_artifacts(older_than_hours: int = 24) -> int:
    """Remove storage artifacts (chunks + final audio) for narrations with no DB row.

    Scans the narrations/ directory and deletes any subdirectory whose ID does not
    exist in the Narration table.  Only removes artifacts older than the given
    threshold to avoid deleting a narration that was just created.  Returns the
    number of orphaned narration directories removed.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    with get_db_context() as db:
        valid_ids = set(
            row[0] for row in db.execute(select(Narration.id)).all()
        )

    removed = 0
    root = storage.root()
    narrations_dir = root / "narrations"
    if not narrations_dir.is_dir():
        return 0

    for path in narrations_dir.iterdir():
        if not path.is_dir():
            continue
        if path.name in valid_ids:
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            mtime = cutoff
        if mtime > cutoff:
            continue
        try:
            storage.shutil.rmtree(path)
            removed += 1
            logger.info("removed orphaned narration artifacts: %s", path.name)
        except OSError as exc:
            logger.warning("failed to remove orphaned artifacts for %s: %s", path.name, exc)

    return removed


def run_cleanup() -> dict[str, int]:
    """Run all maintenance tasks and return a summary of what was done."""
    return {
        "orphaned_chunks_swept": sweep_orphaned_chunks(),
        "stale_jobs_pruned": prune_stale_jobs(),
        "orphaned_artifacts_pruned": prune_orphaned_artifacts(),
    }
