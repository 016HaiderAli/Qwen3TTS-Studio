"""Admin/maintenance endpoints for storage cleanup."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..cleanup import run_cleanup
from ..deps import get_current_user
from ..models import User

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


class CleanupResponse(BaseModel):
    orphaned_chunks_swept: int
    stale_jobs_pruned: int
    orphaned_artifacts_pruned: int


@router.post("/cleanup", response_model=CleanupResponse)
def trigger_cleanup(user: User = Depends(get_current_user)) -> CleanupResponse:
    """Run storage maintenance: prune orphaned chunks, stale jobs, and orphaned artifacts.

    This endpoint is intended for occasional manual invocation or scheduled cron jobs.
    Authentication is required.
    """
    result = run_cleanup()
    return CleanupResponse(**result)
