"""Auth router: Google OAuth (Authorization Code + PKCE), dev login, logout."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth_google
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user
from ..models import Session as SessionModel
from ..models import User
from ..schemas import MeResponse
from ..security import (
    generate_pkce_verifier,
    generate_session_token,
    hash_token,
    pkce_challenge,
    token_expiry,
)

router = APIRouter()
settings = get_settings()

_STATE_COOKIE = "vs_oauth_state"
_STATE_TTL_SECONDS = 600


def _set_state_cookie(response: Response, state: str, verifier: str) -> None:
    payload = json.dumps({"state": state, "verifier": verifier})
    response.set_cookie(
        key=_STATE_COOKIE,
        value=payload,
        max_age=_STATE_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    for name in (settings.session_cookie_name, _STATE_COOKIE):
        response.delete_cookie(key=name, path="/")


@router.get("/auth/login")
def login(response: Response) -> dict:
    if not settings.google_client_id:
        raise HTTPException(
            status_code=503,
            detail="Google authentication is not configured on this server.",
        )
    state = __import__("secrets").token_urlsafe(32)
    verifier = generate_pkce_verifier()
    challenge = pkce_challenge(verifier)
    url = auth_google.build_authorization_url(settings, state, challenge)
    _set_state_cookie(response, state, verifier)
    return {"url": url}


@router.get("/auth/callback")
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    request: Request = None,
    response: Response = None,
    db: Session = Depends(get_db),
):
    """Google OAuth callback.

    ``request``/``response`` are injected by FastAPI; the ``None`` defaults are
    required for FastAPI to treat them as optional-injectable dependencies.
    """
    if error:
        raise HTTPException(status_code=400, detail=f"Google sign-in failed: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing authorization code.")

    stored = request.cookies.get(_STATE_COOKIE)
    if not stored:
        raise HTTPException(status_code=400, detail="OAuth state cookie missing.")
    try:
        payload = json.loads(stored)
        if payload.get("state") != state:
            raise HTTPException(status_code=400, detail="OAuth state mismatch.")
        verifier = payload["verifier"]
    except (json.JSONDecodeError, KeyError):
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")

    identity = await auth_google.google_identity_from_code(code, verifier)

    user = db.execute(
        select(User).where(User.google_sub == identity.sub)
    ).scalar_one_or_none()
    if user is None:
        user = User(
            google_sub=identity.sub,
            email=identity.email,
            name=identity.name,
        )
        db.add(user)
        db.flush()

    token = generate_session_token()
    db.add(
        SessionModel(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=token_expiry(),
        )
    )
    db.commit()

    _set_session_cookie(response, token)
    _clear_cookies(response)
    return response


@router.get("/auth/dev-login")
def dev_login(
    email: str,
    response: Response,
    db: Session = Depends(get_db),
):
    """Test-only login. Disabled unless DEV_LOGIN=1. Never enabled in production."""
    if not settings.dev_login:
        raise HTTPException(status_code=404, detail="Not found.")
    email = email.strip().lower()
    if not email or "@" not in email or len(email) > 320:
        raise HTTPException(status_code=400, detail="Invalid email.")

    user = db.execute(
        select(User).where(User.email == email, User.google_sub == email)
    ).scalar_one_or_none()
    if user is None:
        user = User(google_sub=email, email=email, name=email.split("@")[0])
        db.add(user)
        db.flush()

    token = generate_session_token()
    db.add(
        SessionModel(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=token_expiry(),
        )
    )
    db.commit()
    _set_session_cookie(response, token)
    return {"ok": True}


@router.post("/auth/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        db.execute(
            SessionModel.__table__.delete().where(
                SessionModel.token_hash == hash_token(token)
            )
        )
        db.commit()
    _clear_cookies(response)
    return {"ok": True}


@router.get("/api/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)):
    return user
