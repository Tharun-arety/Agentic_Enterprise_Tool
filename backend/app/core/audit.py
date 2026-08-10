"""Append-only audit log.

This is the configuration status accounting spine: the formal record of what
the product data was, what changed it, who authorised it, and when. Every
service-layer mutation writes one event inside the same transaction as the
change itself, so a committed change without an audit row is not a state the
database can reach.

There is deliberately no update or delete path. Correcting a mistaken entry
means writing a further event that says so.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import enum_values
from app.core.principal import ActorType, Principal


class AuditAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    # State-machine moves (ECR submitted, ECO released) are their own category:
    # the interesting question about a change order is not which columns moved
    # but which gate it passed through.
    TRANSITION = "transition"
    APPROVE = "approve"
    REJECT = "reject"
    LOGIN = "login"


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        # "Show me everything that happened to this ECO" and "show me this
        # week's activity" are the two queries this table exists to answer.
        Index("ix_audit_entity", "entity_type", "entity_id", "occurred_at"),
        Index("ix_audit_occurred", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    actor_type: Mapped[ActorType] = mapped_column(
        SAEnum(
            ActorType,
            name="actor_type",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        )
    )
    # No FK to users: an audit row must survive the deletion of the account
    # that produced it, or the record is not a record.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(128))

    action: Mapped[AuditAction] = mapped_column(
        SAEnum(
            AuditAction,
            name="audit_action",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        )
    )
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))

    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Ties every event produced by one agent turn or one API call together, so
    # a multi-table change reads as one story rather than as scattered rows.
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuditEvent {self.action} {self.entity_type}:{self.entity_id}>"


def record(
    session: AsyncSession,
    *,
    actor: Principal,
    action: AuditAction,
    entity_type: str,
    entity_id: str | uuid.UUID,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    correlation_id: uuid.UUID | None = None,
) -> AuditEvent:
    """Stage an audit event on the caller's session.

    Deliberately not `async` and deliberately not committing: the event must
    land in the same transaction as the mutation it describes. Committing here
    would let a rolled-back change leave a permanent claim that it happened.
    """
    event = AuditEvent(
        actor_type=actor.actor_type,
        actor_id=actor.user_id,
        actor_label=actor.label,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before=before,
        after=after,
        reason=reason,
        correlation_id=correlation_id,
    )
    session.add(event)
    return event
