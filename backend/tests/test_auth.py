"""Auth/session tests: dev login, /me, logout, OAuth callback, authorization."""
from unittest.mock import AsyncMock

from app import auth_google
from app.routers import auth as auth_router


def test_dev_login_sets_session(client, dev_login):
    token = dev_login("alice@example.com")
    assert token
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


def test_me_requires_auth(client):
    resp = client.get("/api/me")
    assert resp.status_code == 401


def test_logout_invalidates_session(client, dev_login):
    dev_login("alice@example.com")
    assert client.get("/api/me").status_code == 200
    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    assert client.get("/api/me").status_code == 401


def test_dev_login_disabled_when_flag_off(client, monkeypatch):
    monkeypatch.setattr(auth_router.settings, "dev_login", False)
    resp = client.get("/auth/dev-login?email=a@b.com")
    assert resp.status_code == 404


def test_oauth_callback_creates_user_and_session(client, monkeypatch):
    identity = auth_google.GoogleIdentity(
        sub="google-sub-1", email="oauth@example.com", name="OAuth User"
    )
    monkeypatch.setattr(
        auth_router.auth_google,
        "google_identity_from_code",
        AsyncMock(return_value=identity),
    )
    # /auth/login requires configured google client id (set in conftest).
    login = client.get("/auth/login")
    assert login.status_code == 200

    # The cookie value is HTTP-cookie-escaped; unquote it via SimpleCookie.
    import http.cookies
    import json

    jar = http.cookies.SimpleCookie()
    jar.load(login.headers["set-cookie"])
    payload = json.loads(jar[auth_router._STATE_COOKIE].value)

    # TestClient already carries the state cookie from /auth/login.
    client.get(f"/auth/callback?code=abc&state={payload['state']}")
    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["email"] == "oauth@example.com"


def test_oauth_callback_rejects_state_mismatch(client):
    client.get("/auth/login")
    resp = client.get("/auth/callback?code=abc&state=wrong-state")
    assert resp.status_code == 400


def test_oauth_login_503_without_client_id(client, monkeypatch):
    monkeypatch.setattr(auth_router.settings, "google_client_id", "")
    resp = client.get("/auth/login")
    assert resp.status_code == 503


def test_google_login_url_contains_pkce_params():
    from app.config import get_settings
    from app.security import generate_pkce_verifier, pkce_challenge

    url = auth_google.build_authorization_url(
        get_settings(), "state123", pkce_challenge(generate_pkce_verifier())
    )
    assert "code_challenge=S256" in url or "code_challenge=" in url
    assert "state=state123" in url
    assert "redirect_uri=" in url
