"""FastAPI dependencies: authentication and authorization."""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import Session as SessionModel
from .models import User
from .security import hash_token

settings = get_settings()

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Authentication required.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise _CREDENTIALS_ERROR
    token_hash = hash_token(token)
    row = db.execute(
        select(SessionModel).where(
            SessionModel.token_hash == token_hash,
            SessionModel.expires_at > datetime.now(timezone.utc),
        )
    ).scalar_one_or_none()
    if row is None:
        raise _CREDENTIALS_ERROR
    user = db.get(User, row.user_id)
    if user is None:
        raise _CREDENTIALS_ERROR
    return user


def require_worker(
    request: Request,
) -> None:
    """Authenticate the GPU worker via a bearer token.

    The worker token is compared with a constant-time comparison. If no worker
    token is configured, internal routes are disabled entirely.
    """
    if not settings.worker_token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Not found."
        )
    auth = request.headers.get("Authorization", "")
    expected = f"Bearer {settings.worker_token}"
    if not _safe_equal(auth, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid worker credentials.",
        )


def _safe_equal(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    import secrets as _secrets

    return _secrets.compare_digest(a, b)
