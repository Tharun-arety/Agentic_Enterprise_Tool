"""Authentication against the database."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, AuditEvent
from app.domains.identity.models import Role, User
from app.domains.identity.service import AuthError, authenticate

pytestmark = pytest.mark.db


async def test_valid_credentials_return_the_user(
    session: AsyncSession, user_factory
) -> None:
    created: User = await user_factory(Role.QUALITY, email="q@magnotherm.test")
    user = await authenticate(session, "q@magnotherm.test", "correct-horse")
    assert user.id == created.id
    assert user.roles == [Role.QUALITY.value]


async def test_email_match_is_case_insensitive(
    session: AsyncSession, user_factory
) -> None:
    await user_factory(Role.ENGINEER, email="mixed@magnotherm.test")
    user = await authenticate(session, "  MiXeD@Magnotherm.TEST ", "correct-horse")
    assert user.email == "mixed@magnotherm.test"


async def test_wrong_password_is_refused(session: AsyncSession, user_factory) -> None:
    await user_factory(Role.ENGINEER, email="e@magnotherm.test")
    with pytest.raises(AuthError):
        await authenticate(session, "e@magnotherm.test", "wrong")


async def test_unknown_address_gives_the_same_message_as_a_wrong_password(
    session: AsyncSession, user_factory
) -> None:
    # Distinguishable errors would turn the login endpoint into an account
    # enumeration oracle.
    await user_factory(Role.ENGINEER, email="known@magnotherm.test")
    with pytest.raises(AuthError) as wrong_password:
        await authenticate(session, "known@magnotherm.test", "wrong")
    with pytest.raises(AuthError) as unknown_user:
        await authenticate(session, "nobody@magnotherm.test", "wrong")
    assert str(wrong_password.value) == str(unknown_user.value)


async def test_disabled_account_cannot_sign_in(
    session: AsyncSession, user_factory
) -> None:
    await user_factory(Role.ENGINEER, email="gone@magnotherm.test", active=False)
    with pytest.raises(AuthError, match="disabled"):
        await authenticate(session, "gone@magnotherm.test", "correct-horse")


async def test_successful_login_is_audited(
    session: AsyncSession, user_factory
) -> None:
    user = await user_factory(Role.QUALITY, email="audited@magnotherm.test")
    await authenticate(session, "audited@magnotherm.test", "correct-horse")

    events = (
        await session.execute(
            select(AuditEvent).where(AuditEvent.action == AuditAction.LOGIN)
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].entity_id == str(user.id)
    assert events[0].actor_label == "audited@magnotherm.test"


async def test_failed_login_is_not_audited_as_a_login(
    session: AsyncSession, user_factory
) -> None:
    await user_factory(Role.ENGINEER, email="failer@magnotherm.test")
    with pytest.raises(AuthError):
        await authenticate(session, "failer@magnotherm.test", "wrong")
    count = await session.scalar(select(func.count()).select_from(AuditEvent))
    assert count == 0


def test_admin_satisfies_every_role_check() -> None:
    admin = User(email="a@b.test", full_name="A", password_hash="x", roles=["admin"])
    assert admin.has_role(Role.QUALITY)
    assert admin.has_role(Role.PROCUREMENT)

    quality = User(email="q@b.test", full_name="Q", password_hash="x", roles=["quality"])
    assert quality.has_role(Role.QUALITY)
    assert not quality.has_role(Role.PROCUREMENT)
