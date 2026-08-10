from __future__ import annotations
import uuid
from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
class LabAsset(Base):
    __tablename__="lab_assets"; id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); asset_tag: Mapped[str]=mapped_column(String(32),unique=True,index=True); name: Mapped[str]=mapped_column(String(160)); location: Mapped[str]=mapped_column(String(80)); status: Mapped[str]=mapped_column(String(24),default="available"); calibration_interval_days: Mapped[int]=mapped_column(Integer,default=365); external_id: Mapped[str|None]=mapped_column(String(128))
class CalibrationCertificate(Base):
    __tablename__="calibration_certificates"; id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); asset_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("lab_assets.id",ondelete="CASCADE"),index=True); certificate_number: Mapped[str]=mapped_column(String(64),unique=True); calibrated_at: Mapped[date]=mapped_column(Date); valid_until: Mapped[date]=mapped_column(Date,index=True); document_revision_id: Mapped[uuid.UUID|None]=mapped_column(PGUUID(as_uuid=True),ForeignKey("document_revisions.id")); result: Mapped[str]=mapped_column(String(24),default="pass")
class AssetBooking(Base):
    __tablename__="asset_bookings"; id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); asset_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("lab_assets.id",ondelete="CASCADE"),index=True); starts_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True); ends_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True); booked_by: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True)); purpose: Mapped[str]=mapped_column(Text); status: Mapped[str]=mapped_column(String(24),default="confirmed")
class TestAssetUsage(Base):
    __tablename__="test_asset_usage"; id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); test_record_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("lab_test_records.id",ondelete="CASCADE"),index=True); asset_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("lab_assets.id")); calibration_certificate_id: Mapped[uuid.UUID|None]=mapped_column(PGUUID(as_uuid=True),ForeignKey("calibration_certificates.id")); valid_at_test: Mapped[bool]=mapped_column(default=False); invalid_reason: Mapped[str|None]=mapped_column(Text)
