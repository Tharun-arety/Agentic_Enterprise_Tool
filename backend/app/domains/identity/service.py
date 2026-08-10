"""Authentication."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.audit import AuditAction
from app.core.principal import ActorType, Principal
from app.core.security import hash_password, verify_password
from app.domains.identity.models import User

logger = logging.getLogger(__name__)

# A real Argon2 hash of a value no password will equal, so that verifying
# against it costs the same as verifying a genuine one. Computed once at import,
# because hashing per request would cost more than the verify it mirrors, and an
# invalid placeholder string would fail fast and reintroduce the timing gap it
# exists to close.
_DUMMY_HASH = hash_password("no-account-with-this-password")


class AuthError(Exception):
    """Credentials were not accepted."""


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    """Return the user for valid credentials, else raise.

    The same message is returned whether the address is unknown or the password
    is wrong, so the endpoint cannot be used to enumerate who has an account.
    """
    user = (
        await session.execute(select(User).where(User.email == email.strip().lower()))
    ).scalar_one_or_none()

    # Verify even when the user is missing, against a hash that cannot match,
    # so a nonexistent address costs the same time as a real one. Skipping the
    # work would leak account existence through response timing.
    candidate_hash = user.password_hash if user else _DUMMY_HASH
    password_ok = verify_password(password, candidate_hash)

    if user is None or not password_ok:
        raise AuthError("Email or password is incorrect.")
    if not user.is_active:
        raise AuthError("This account is disabled.")

    audit.record(
        session,
        actor=Principal(
            actor_type=ActorType.HUMAN,
            user_id=user.id,
            email=user.email,
            roles=tuple(user.roles),
        ),
        action=AuditAction.LOGIN,
        entity_type="User",
        entity_id=user.id,
    )
    await session.commit()
    return user
