from __future__ import annotations
import asyncio
from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from app.core.config import get_settings
from app.core.db import get_session_factory
from app.domains.backoffice.adapters import ErpnextBackofficeAdapter,LocalBackofficeAdapter
from app.domains.backoffice.dto import ItemDTO
from app.domains.backoffice.models import IntegrationOutbox
async def process_batch(limit=50):
    async with get_session_factory()() as session:
        rows=(await session.execute(select(IntegrationOutbox).where(IntegrationOutbox.status=="pending",(IntegrationOutbox.next_attempt_at.is_(None))|(IntegrationOutbox.next_attempt_at<=datetime.now(timezone.utc))).order_by(IntegrationOutbox.created_at).with_for_update(skip_locked=True).limit(limit))).scalars().all()
        adapter=ErpnextBackofficeAdapter() if get_settings().backoffice_adapter=="erpnext" else LocalBackofficeAdapter(session)
        for row in rows:
            row.status="processing"; row.attempts+=1
            try:
                if row.topic=="pdm.item.released": await adapter.upsert_item(ItemDTO.model_validate(row.payload))
                # Other events are integration notifications consumed by
                # reconciliation/webhook workflows; successful handoff is
                # still explicit and idempotent.
                row.status="delivered"; row.delivered_at=datetime.now(timezone.utc); row.last_error=None
            except Exception as exc:
                row.last_error=f"{type(exc).__name__}: {exc}"[:2000]
                if row.attempts>=8: row.status="dead_letter"
                else: row.status="pending"; row.next_attempt_at=datetime.now(timezone.utc)+timedelta(seconds=min(3600,2**row.attempts*15))
        await session.commit(); return len(rows)
async def main():
    while True:
        count=await process_batch()
        if not count: await asyncio.sleep(2)
if __name__=="__main__": asyncio.run(main())
