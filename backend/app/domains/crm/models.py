from __future__ import annotations
import uuid
from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base

class Lead(Base):
    __tablename__="crm_leads"
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    name: Mapped[str]=mapped_column(String(160)); company: Mapped[str]=mapped_column(String(160)); status: Mapped[str]=mapped_column(String(24),default="new",index=True)
class Opportunity(Base):
    __tablename__="crm_opportunities"
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    title: Mapped[str]=mapped_column(String(200)); customer_name: Mapped[str]=mapped_column(String(160)); stage: Mapped[str]=mapped_column(String(32),index=True); value: Mapped[float]=mapped_column(Numeric(14,2),default=0); currency: Mapped[str]=mapped_column(String(3),default="EUR"); expected_close: Mapped[date|None]=mapped_column(Date)
class CustomerSite(Base):
    __tablename__="customer_sites"
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    customer_name: Mapped[str]=mapped_column(String(160),index=True); site_name: Mapped[str]=mapped_column(String(160)); address: Mapped[str|None]=mapped_column(Text)
class DeployedUnit(Base):
    __tablename__="deployed_units"
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    unit_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("units.id"),unique=True,index=True); customer_site_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("customer_sites.id"),index=True); commissioned_at: Mapped[date|None]=mapped_column(Date); status: Mapped[str]=mapped_column(String(24),default="operational")
class FieldEvent(Base):
    __tablename__="field_events"
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    deployed_unit_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("deployed_units.id",ondelete="CASCADE"),index=True); occurred_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now()); event_type: Mapped[str]=mapped_column(String(32),index=True); summary: Mapped[str]=mapped_column(Text); resolution: Mapped[str|None]=mapped_column(Text)
