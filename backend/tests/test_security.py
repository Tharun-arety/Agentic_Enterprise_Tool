"""Password hashing and token handling — no database required."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_is_salted_and_verifies() -> None:
    first = hash_password("correct-horse")
    second = hash_password("correct-horse")
    # Distinct hashes for the same password is the salt doing its job; equal
    # hashes would mean the store is a rainbow-table lookup away from useless.
    assert first != second
    assert verify_password("correct-horse", first)
    assert verify_password("correct-horse", second)


def test_wrong_password_returns_false_rather_than_raising() -> None:
    assert verify_password("wrong", hash_password("correct-horse")) is False


def test_corrupt_hash_returns_false_rather_than_raising() -> None:
    # A truncated row in the users table must read as "do not log in", not as a
    # 500 that reveals the store is damaged.
    assert verify_password("anything", "$argon2id$broken") is False


def test_token_round_trip_carries_roles() -> None:
    subject = uuid.uuid4()
    token, expires_in = create_access_token(
        subject=subject, email="a@b.test", roles=["quality", "engineer"]
    )
    claims = decode_access_token(token)
    assert claims["sub"] == str(subject)
    assert claims["email"] == "a@b.test"
    assert claims["roles"] == ["quality", "engineer"]
    assert expires_in == get_settings().jwt_expiry_minutes * 60


def test_expired_token_is_rejected() -> None:
    settings = get_settings()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": int(past.timestamp())},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(TokenError, match="expired"):
        decode_access_token(token)


def test_token_signed_with_another_key_is_rejected() -> None:
    settings = get_settings()
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "roles": ["admin"],
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        },
        # Long enough not to trip PyJWT's short-key warning; the point of the
        # test is the wrong key, not a weak one.
        "not-the-real-signing-key-but-long-enough-to-be-plausible",
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(TokenError):
        decode_access_token(forged)
