from __future__ import annotations
import uuid
from datetime import date
from sqlalchemy import Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
class EngineerCapacity(Base):
    __tablename__="engineer_capacity"; id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); user_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("users.id"),index=True); week_start: Mapped[date]=mapped_column(Date,index=True); available_hours: Mapped[float]=mapped_column(Numeric(8,2),default=40)
class ResourceAllocation(Base):
    __tablename__="resource_allocations"; id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); user_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("users.id"),index=True); work_package_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("work_packages.id"),index=True); week_start: Mapped[date]=mapped_column(Date,index=True); allocated_hours: Mapped[float]=mapped_column(Numeric(8,2)); notes: Mapped[str|None]=mapped_column(Text)
class TimesheetEntry(Base):
    __tablename__="timesheet_entries"; id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); user_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("users.id"),index=True); work_package_id: Mapped[uuid.UUID|None]=mapped_column(PGUUID(as_uuid=True),ForeignKey("work_packages.id")); work_date: Mapped[date]=mapped_column(Date,index=True); hours: Mapped[float]=mapped_column(Numeric(8,2)); description: Mapped[str|None]=mapped_column(Text); external_id: Mapped[str|None]=mapped_column(String(128))
