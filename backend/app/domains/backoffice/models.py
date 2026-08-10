from __future__ import annotations
import enum, uuid
from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


class DeliveryState(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    DEAD_LETTER = "dead_letter"


class ExternalReference(Base):
    __tablename__ = "external_references"
    __table_args__ = (UniqueConstraint("system", "entity_type", "local_id", name="uq_external_reference"),)
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    system: Mapped[str] = mapped_column(String(32), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    local_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    external_id: Mapped[str] = mapped_column(String(256), index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationOutbox(Base):
    __tablename__ = "integration_outbox"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(128), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(24), default=DeliveryState.PENDING.value, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookInbox(Base):
    __tablename__ = "webhook_inbox"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(32))
    event_id: Mapped[str] = mapped_column(String(128), unique=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(24), default="received", index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
