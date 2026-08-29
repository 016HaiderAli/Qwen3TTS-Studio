"""Auth router: Google OAuth (Authorization Code + PKCE), dev login, logout."""
import base64
import binascii
import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
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


def _encode_state_payload(state: str, verifier: str) -> str:
    """Encode the OAuth state payload as base64(JSON).

    The raw JSON contains commas and double quotes that ``http.cookies``
    escapes (commas become ``\\054``) per the old Netscape cookie spec; some
    browsers do not unescape those reliably when the value is read back via
    JavaScript, which made the callback fail with ``Invalid OAuth state.``.
    Base64-encoding the JSON makes the cookie value contain only URL-safe
    characters that pass through unmodified.
    """
    raw = json.dumps({"state": state, "verifier": verifier}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_state_payload(value: str) -> dict | None:
    """Decode the OAuth state payload, tolerating the legacy raw-JSON form.

    Returns ``None`` if the value is neither valid base64-JSON nor a valid raw
    JSON object with the expected keys.
    """
    if not value:
        return None
    candidates: list[str] = [value]
    # Tolerate cookies that were stored with a wrapping pair of double quotes
    # (Starlette's SimpleCookie behaviour for the original raw-JSON form).
    if value.startswith('"') and value.endswith('"'):
        candidates.append(value[1:-1])
    # Tolerate the legacy Netscape ``\054`` comma escape, in case the cookie
    # was set by an older backend and the browser returned the value
    # unescaped-as-JSON instead of base64.
    candidates.append(value.replace("\\054", ","))
    for raw in candidates:
        # 1) try base64-JSON
        try:
            pad = "=" * (-len(raw) % 4)
            decoded = base64.urlsafe_b64decode((raw + pad).encode("ascii"))
            data = json.loads(decoded)
            if isinstance(data, dict) and "state" in data and "verifier" in data:
                return data
        except (binascii.Error, ValueError, json.JSONDecodeError):
            pass
        # 2) try raw JSON
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "state" in data and "verifier" in data:
                return data
        except json.JSONDecodeError:
            pass
    return None


def _set_state_cookie(response: Response, state: str, verifier: str) -> None:
    response.set_cookie(
        key=_STATE_COOKIE,
        value=_encode_state_payload(state, verifier),
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
    payload = _decode_state_payload(stored)
    if payload is None:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")
    if payload.get("state") != state:
        raise HTTPException(status_code=400, detail="OAuth state mismatch.")
    verifier = payload["verifier"]

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
    # Redirect the browser to the frontend so the SPA picks up the new
    # session cookie. Using 303 so the browser issues a GET (the SPA route),
    # not whatever method Google used for the callback.
    #
    # Important: we cannot return the injected ``response`` here (FastAPI
    # cannot JSON-serialize it, which is the original 500 bug). We also
    # cannot rely on Starlette's ``MutableHeaders`` to forward the cookies
    # already set on the injected response — ``append('set-cookie', ...)``
    # combines multiple Set-Cookie values into a single comma-joined header,
    # which RFC 6265 says browsers should reject. The reliable way is to
    # set the cookies directly on the RedirectResponse we are returning.
    frontend_origin = (settings.frontend_url or "").rstrip("/")
    target = f"{frontend_origin}/voices" if frontend_origin else "/voices"
    redirect = RedirectResponse(url=target, status_code=303)
    redirect.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    redirect.delete_cookie(key=_STATE_COOKIE, path="/")
    return redirect


@router.get("/auth/dev-login")
@router.post("/auth/dev-login")
def dev_login(
    email: str,
    response: Response,
    db: Session = Depends(get_db),
):
    """Test-only login. Disabled unless DEV_LOGIN=1. Never enabled in production.

    Accepts both GET (so a one-click URL like
    ``/auth/dev-login?email=you@example.com`` works in a browser) and POST
    (so the React UI can call it from ``fetch`` and read the JSON response).
    """
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
