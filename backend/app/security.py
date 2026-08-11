"""Token generation, hashing, and session helpers."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from .config import get_settings


def generate_session_token() -> str:
    """Return a cryptographically random opaque session token."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Return the hex SHA-256 of a session token (what is stored in the DB)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_expiry() -> datetime:
    settings = get_settings()
    return datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds)


def generate_pkce_verifier() -> str:
    return secrets.token_urlsafe(64)


def pkce_challenge(verifier: str) -> str:
    """S256 PKCE challenge derived from the verifier (no external deps)."""
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return _b64url(digest)


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")
