from datetime import datetime
from sqlalchemy import and_,or_,select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.assets.models import AssetBooking,CalibrationCertificate
from app.tools.registry import ToolError
async def calibration_valid(session:AsyncSession,asset_id,at:datetime):
    cert=(await session.execute(select(CalibrationCertificate).where(CalibrationCertificate.asset_id==asset_id,CalibrationCertificate.calibrated_at<=at.date(),CalibrationCertificate.valid_until>=at.date(),CalibrationCertificate.result=="pass").order_by(CalibrationCertificate.valid_until.desc()))).scalars().first(); return cert
async def book(session:AsyncSession,asset_id,starts_at,ends_at,user_id,purpose):
    if ends_at<=starts_at: raise ToolError("Booking end must be after start.")
    conflict=(await session.execute(select(AssetBooking).where(AssetBooking.asset_id==asset_id,AssetBooking.status=="confirmed",AssetBooking.starts_at<ends_at,AssetBooking.ends_at>starts_at))).scalars().first()
    if conflict: raise ToolError(f"Asset is already booked from {conflict.starts_at} to {conflict.ends_at}.")
    row=AssetBooking(asset_id=asset_id,starts_at=starts_at,ends_at=ends_at,booked_by=user_id,purpose=purpose); session.add(row); await session.commit(); return row
