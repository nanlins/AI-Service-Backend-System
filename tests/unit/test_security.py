import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.errors import AuthError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("secret123")
    assert hashed != "secret123"
    assert verify_password("secret123", hashed)
    assert not verify_password("wrong", hashed)


def test_password_long_input_truncated_safely():
    long_pw = "a" * 200
    hashed = hash_password(long_pw)
    assert verify_password(long_pw, hashed)


def test_verify_rejects_malformed_hash():
    assert not verify_password("anything", "not-a-valid-hash")


def test_jwt_roundtrip():
    token = create_access_token(42)
    payload = decode_access_token(token)
    assert payload["sub"] == "42"


def test_jwt_invalid_token_raises_auth_error():
    with pytest.raises(AuthError):
        decode_access_token("invalid.token.value")


def test_jwt_expired_token_raises_auth_error():
    token = create_access_token(1, expires_minutes=-1)
    with pytest.raises(AuthError):
        decode_access_token(token)


def test_jwt_wrong_secret_rejected():
    original = settings.jwt_secret
    token = create_access_token(1)
    settings.jwt_secret = SecretStr("other-secret-fedcba9876543210fedcba9876543210")
    try:
        with pytest.raises(AuthError):
            decode_access_token(token)
    finally:
        settings.jwt_secret = original
