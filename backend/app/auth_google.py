"""Google OAuth 2.0 Authorization Code + PKCE client.

The HTTP transport is injectable so tests can exercise the flow without
network access.
"""
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .config import Settings, get_settings


class OAuthError(Exception):
    pass


@dataclass
class GoogleIdentity:
    sub: str
    email: str
    name: str
    email_verified: bool = False


def build_authorization_url(
    settings: Settings,
    state: str,
    code_challenge: str,
) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.resolved_redirect_uri,
        "response_type": "code",
        "scope": settings.google_scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{settings.google_auth_uri}?{urlencode(params)}"


async def exchange_code(
    settings: Settings,
    code: str,
    code_verifier: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Exchange an authorization code for an access token. Returns access token."""
    payload = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.resolved_redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.post(settings.google_token_uri, data=payload)
    if resp.status_code != 200:
        raise OAuthError(f"token exchange failed: HTTP {resp.status_code}")
    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise OAuthError("token exchange response missing access_token")
    return access_token


async def fetch_userinfo(
    settings: Settings,
    access_token: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> GoogleIdentity:
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await client.get(
            settings.google_userinfo_uri,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        raise OAuthError(f"userinfo failed: HTTP {resp.status_code}")
    data = resp.json()
    sub = data.get("sub")
    email = data.get("email")
    if not sub or not email:
        raise OAuthError("userinfo missing sub/email")
    return GoogleIdentity(
        sub=str(sub),
        email=str(email),
        name=str(data.get("name") or ""),
        email_verified=bool(data.get("email_verified", False)),
    )


async def google_identity_from_code(
    code: str,
    code_verifier: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> GoogleIdentity:
    settings = get_settings()
    access_token = await exchange_code(settings, code, code_verifier, transport)
    return await fetch_userinfo(settings, access_token, transport)
