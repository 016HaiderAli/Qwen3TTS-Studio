"""Unit tests for security helpers."""
from app.security import (
    generate_pkce_verifier,
    generate_session_token,
    hash_token,
    pkce_challenge,
)


def test_session_token_unique_and_opaque():
    a = generate_session_token()
    b = generate_session_token()
    assert a != b
    assert len(a) >= 32
    assert a.isalnum() or "-" in a or "_" in a


def test_hash_token_deterministic_and_not_plaintext():
    token = "super-secret-token"
    assert hash_token(token) == hash_token(token)
    assert hash_token(token) != token
    assert len(hash_token(token)) == 64


def test_pkce_verifier_and_challenge():
    v = generate_pkce_verifier()
    assert len(v) >= 40
    c = pkce_challenge(v)
    assert c != v
    assert len(c) == 43  # SHA-256 S256 challenge without padding
    assert pkce_challenge(v) == pkce_challenge(v)
