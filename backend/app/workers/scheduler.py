from __future__ import annotations
import asyncio
from datetime import date,datetime,timedelta,timezone
from sqlalchemy import select
from app.core.db import get_session_factory
from app.domains.assets.models import AssetBooking,CalibrationCertificate
from app.domains.procurement.service import supply_risk
from app.workers.models import AutomationFinding
async def _finding(session,key,detector,severity,title,evidence):
    if not (await session.execute(select(AutomationFinding).where(AutomationFinding.idempotency_key==key))).scalar_one_or_none(): session.add(AutomationFinding(idempotency_key=key,detector=detector,severity=severity,title=title,evidence=evidence))
async def run_detectors():
    async with get_session_factory()() as session:
        today=date.today(); certs=(await session.execute(select(CalibrationCertificate).where(CalibrationCertificate.valid_until<=today+timedelta(days=30)))).scalars()
        for c in certs: await _finding(session,f"calibration:{c.id}:{c.valid_until}","calibration","high" if c.valid_until<today else "medium","Calibration due",{"certificate":c.certificate_number,"valid_until":str(c.valid_until)})
        for x in await supply_risk(session):
            if x["low_stock"]: await _finding(session,f"low-stock:{x['part_number']}:{today}","low_stock","medium",f"Low stock: {x['part_number']}",x)
        bookings=(await session.execute(select(AssetBooking).where(AssetBooking.ends_at>datetime.now(timezone.utc)))).scalars().all()
        for a in bookings:
            for b in bookings:
                if a.id<b.id and a.asset_id==b.asset_id and a.starts_at<b.ends_at and b.starts_at<a.ends_at: await _finding(session,f"booking-conflict:{a.id}:{b.id}","booking_conflict","high","Asset booking conflict",{"bookings":[str(a.id),str(b.id)]})
        await session.commit()
async def main():
    while True: await run_detectors(); await asyncio.sleep(300)
if __name__=="__main__": asyncio.run(main())
