"""Password hashing and JWT issue/verify.

Argon2id is used directly through `argon2-cffi` rather than through passlib:
passlib imports the stdlib `crypt` module, which was removed in Python 3.13, so
it is a dependency with a known expiry date on a project that will outlive it.

Tokens are symmetric (HS256) and short-lived. Asymmetric signing buys key
distribution across services, which a single-service deployment does not need.
"""

from __future__ import annotations

import logging
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_hasher = PasswordHasher()


class TokenError(Exception):
    """The presented token was missing, malformed, expired, or badly signed."""


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time check that never raises on a wrong password.

    argon2-cffi signals a mismatch by exception; converting that to `False` here
    keeps the caller from having to distinguish "wrong password" from "corrupt
    hash" at the call site, where both mean the same thing: do not log them in.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(
    *, subject: uuid.UUID, email: str, roles: list[str]
) -> tuple[str, int]:
    """Return `(token, expires_in_seconds)` for an authenticated user."""
    settings = get_settings()
    lifetime = timedelta(minutes=settings.jwt_expiry_minutes)
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "email": email,
        "roles": roles,
        "type": "access",
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        if payload.get("type", "access") != "access":
            raise TokenError("The presented token is not an access token.")
        return payload
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired; sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError(f"Token is not valid: {exc}") from exc


def new_refresh_token() -> str:
    """Return a high-entropy opaque refresh credential."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
