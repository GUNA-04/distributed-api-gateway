"""
Unit tests for JWT authentication and password hashing.
"""
import pytest
from datetime import timedelta
from fastapi import HTTPException

from gateway.app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("super-secret-123")
    assert hashed != "super-secret-123"
    assert verify_password("super-secret-123", hashed) is True


def test_password_wrong_password_fails():
    hashed = hash_password("super-secret-123")
    assert verify_password("wrong-password", hashed) is False


def test_password_hashes_are_salted():
    """Two hashes of the same password must differ (bcrypt salt)."""
    assert hash_password("super-secret-123") != hash_password("super-secret-123")


def test_jwt_roundtrip():
    token = create_access_token(data={"sub": "123e4567-e89b-12d3-a456-426614174000", "tier": "free"})
    payload = decode_token(token)
    assert payload["sub"] == "123e4567-e89b-12d3-a456-426614174000"
    assert payload["tier"] == "free"
    assert "exp" in payload and "iat" in payload


def test_jwt_expired_token_rejected():
    token = create_access_token(
        data={"sub": "user"},
        expires_delta=timedelta(seconds=-10),
    )
    with pytest.raises(HTTPException) as exc:
        decode_token(token)
    assert exc.value.status_code == 401


def test_jwt_garbage_token_rejected():
    with pytest.raises(HTTPException) as exc:
        decode_token("not-a-real-token")
    assert exc.value.status_code == 401


def test_jwt_wrong_secret_rejected():
    from common.app.config import settings
    token = create_access_token(data={"sub": "user"})
    original_key = settings.SECRET_KEY
    settings.SECRET_KEY = "a-completely-different-secret"
    try:
        with pytest.raises(HTTPException) as exc:
            decode_token(token)
        assert exc.value.status_code == 401
    finally:
        settings.SECRET_KEY = original_key
