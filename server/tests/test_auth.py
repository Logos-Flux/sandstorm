"""Tests for the OAuth HMAC helpers — wire-compat with the worker."""

from __future__ import annotations

import base64
import hashlib
import secrets

from sandstorm_mcp import auth


def test_raw_bearer_is_accepted() -> None:
    ctx = auth.verify_bearer("secret", "secret")
    assert ctx is not None
    assert ctx.is_oauth is False
    assert ctx.client_id is None


def test_wrong_bearer_is_rejected() -> None:
    assert auth.verify_bearer("secret", "different") is None
    assert auth.verify_bearer("secret", "") is None


def test_oauth_flow_roundtrip() -> None:
    token = "secret"
    verifier = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )

    code = auth.create_auth_code(token, "client-1", challenge, "S256", "https://x/cb")
    access = auth.exchange_auth_code(token, code, "client-1", verifier, "https://x/cb")
    assert access is not None

    ctx = auth.verify_bearer(token, access)
    assert ctx is not None
    assert ctx.is_oauth is True
    assert ctx.client_id == "client-1"


def test_oauth_wrong_verifier_is_rejected() -> None:
    token = "secret"
    verifier = "a" * 32
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    code = auth.create_auth_code(token, "c", challenge, "S256", "https://x/cb")
    assert (
        auth.exchange_auth_code(token, code, "c", "wrong-verifier", "https://x/cb")
        is None
    )


def test_oauth_wrong_redirect_uri_is_rejected() -> None:
    token = "secret"
    verifier = "a" * 32
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    code = auth.create_auth_code(token, "c", challenge, "S256", "https://x/cb")
    assert auth.exchange_auth_code(token, code, "c", verifier, "https://y/cb") is None


def test_client_id_is_deterministic() -> None:
    a = auth.register_client("secret", "claude.ai", ["https://x/cb"])
    b = auth.register_client("secret", "claude.ai", ["https://x/cb"])
    assert a["client_id"] == b["client_id"]


def test_client_id_changes_with_token() -> None:
    a = auth.register_client("secret1", "claude.ai", ["https://x/cb"])
    b = auth.register_client("secret2", "claude.ai", ["https://x/cb"])
    assert a["client_id"] != b["client_id"]
