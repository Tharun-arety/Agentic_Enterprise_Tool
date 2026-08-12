"""Lab asset reads, shared by the REST router and the agent tools."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.assets.models import AssetBooking, CalibrationCertificate, LabAsset
from app.domains.identity.models import User

#: Certificates expiring inside this window are flagged before they lapse,
#: because recalibration has to be booked in advance to avoid idling a rig.
DUE_SOON_DAYS = 30


async def list_assets(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(LabAsset).order_by(LabAsset.asset_tag))).scalars().all()
    return [
        {
            "id": str(asset.id),
            "asset_tag": asset.asset_tag,
            "name": asset.name,
            "location": asset.location,
            "status": asset.status,
            "calibration_interval_days": asset.calibration_interval_days,
        }
        for asset in rows
    ]


async def list_calibration(session: AsyncSession) -> list[dict[str, Any]]:
    today: date = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=DUE_SOON_DAYS)
    rows = (
        await session.execute(
            select(CalibrationCertificate, LabAsset)
            .join(LabAsset, LabAsset.id == CalibrationCertificate.asset_id)
            .order_by(CalibrationCertificate.valid_until)
        )
    ).all()
    return [
        {
            "id": str(certificate.id),
            "asset_tag": asset.asset_tag,
            "asset_name": asset.name,
            "location": asset.location,
            "certificate_number": certificate.certificate_number,
            "calibrated_at": certificate.calibrated_at,
            "valid_until": certificate.valid_until,
            "result": certificate.result,
            "overdue": certificate.valid_until < today,
            "due_soon": today <= certificate.valid_until < horizon,
            "days_remaining": (certificate.valid_until - today).days,
        }
        for certificate, asset in rows
    ]


async def list_bookings(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(AssetBooking, LabAsset, User.full_name)
            .join(LabAsset, LabAsset.id == AssetBooking.asset_id)
            .outerjoin(User, User.id == AssetBooking.booked_by)
            .order_by(AssetBooking.starts_at)
        )
    ).all()
    return [
        {
            "id": str(booking.id),
            "asset_tag": asset.asset_tag,
            "asset_name": asset.name,
            "starts_at": booking.starts_at,
            "ends_at": booking.ends_at,
            "booked_by": booked_by,
            "purpose": booking.purpose,
            "status": booking.status,
        }
        for booking, asset, booked_by in rows
    ]
