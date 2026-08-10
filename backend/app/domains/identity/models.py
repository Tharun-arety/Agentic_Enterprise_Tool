"""Users and the roles that gate engineering change approvals.

Roles are stored as a Postgres text array rather than a join table. A user has
a handful of roles, they are read on every authenticated request and written
almost never, and the array travels straight into the JWT claim. A join table
would add a query to the hot path to buy a normalisation nobody needs at this
cardinality.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Role(str, enum.Enum):
    """What a user is allowed to do.

    The four CCB roles (`SYSTEMS_ENGINEERING`, `QUALITY`, `MANUFACTURING`,
    `PROCUREMENT`) mirror the cross-functional board composition the ECM
    process requires: a change that helps one function must not quietly cripple
    another, so each has its own seat and its own vote.
    """

    ENGINEER = "engineer"
    SYSTEMS_ENGINEERING = "systems_engineering"
    QUALITY = "quality"
    MANUFACTURING = "manufacturing"
    PROCUREMENT = "procurement"
    CONTROLLER = "controller"
    ADMIN = "admin"


# The seats that must be represented for a Change Control Board decision to
# carry. Referenced by the ECM quorum check and by the seed script.
CCB_ROLES: tuple[Role, ...] = (
    Role.SYSTEMS_ENGINEERING,
    Role.QUALITY,
    Role.MANUFACTURING,
    Role.PROCUREMENT,
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(256))
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def has_role(self, role: Role) -> bool:
        return role.value in self.roles or Role.ADMIN.value in self.roles

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<User {self.email}>"


class RefreshSession(Base):
    """One rotating browser refresh credential; only its SHA-256 is stored."""

    __tablename__ = "refresh_sessions"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    family_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class AccessTokenRevocation(Base):
    __tablename__ = "access_token_revocations"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
