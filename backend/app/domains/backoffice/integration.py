from __future__ import annotations
import hashlib, hmac, json
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.backoffice.models import IntegrationOutbox, WebhookInbox


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_payload(payload)).hexdigest()


def verify_frappe_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    supplied = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, supplied)


async def enqueue(session: AsyncSession, topic: str, aggregate_id: str, payload: dict[str, Any], idempotency_key: str) -> IntegrationOutbox:
    existing = (await session.execute(select(IntegrationOutbox).where(IntegrationOutbox.idempotency_key == idempotency_key))).scalar_one_or_none()
    if existing:
        return existing
    row = IntegrationOutbox(topic=topic, aggregate_id=aggregate_id, payload=payload, payload_hash=payload_hash(payload), idempotency_key=idempotency_key)
    session.add(row)
    await session.flush()
    return row


async def inbox_once(session: AsyncSession, source: str, event_id: str, event_type: str, payload: dict[str, Any]) -> tuple[WebhookInbox, bool]:
    existing = (await session.execute(select(WebhookInbox).where(WebhookInbox.event_id == event_id))).scalar_one_or_none()
    if existing:
        return existing, False
    row = WebhookInbox(source=source, event_id=event_id, event_type=event_type, payload=payload, payload_hash=payload_hash(payload))
    session.add(row)
    await session.commit()
    return row, True


async def queue_depth(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(IntegrationOutbox).where(IntegrationOutbox.status.in_(["pending", "processing"]))) or 0)
