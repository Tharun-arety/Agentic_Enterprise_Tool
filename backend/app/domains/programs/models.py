from __future__ import annotations
import uuid
from datetime import date
from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
class Program(Base):
    __tablename__="programs"; id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); code: Mapped[str]=mapped_column(String(32),unique=True,index=True); name: Mapped[str]=mapped_column(String(160)); status: Mapped[str]=mapped_column(String(24),default="active")
class WorkPackage(Base):
    __tablename__="work_packages"; id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); program_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("programs.id",ondelete="CASCADE"),index=True); code: Mapped[str]=mapped_column(String(32),index=True); title: Mapped[str]=mapped_column(String(200)); budget: Mapped[float]=mapped_column(Numeric(14,2),default=0); trl_target: Mapped[int]=mapped_column(Integer,default=5)
class TrlGate(Base):
    __tablename__="trl_gates"; __table_args__=(UniqueConstraint("work_package_id","trl",name="uq_trl_gate"),); id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); work_package_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("work_packages.id",ondelete="CASCADE"),index=True); trl: Mapped[int]=mapped_column(Integer); status: Mapped[str]=mapped_column(String(24),default="planned"); evidence: Mapped[str|None]=mapped_column(Text); approved_by: Mapped[uuid.UUID|None]=mapped_column(PGUUID(as_uuid=True))
class ConsortiumPartner(Base):
    __tablename__="consortium_partners"; id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); program_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("programs.id",ondelete="CASCADE"),index=True); name: Mapped[str]=mapped_column(String(160)); role: Mapped[str]=mapped_column(String(160))
class Deliverable(Base):
    __tablename__="deliverables"; id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); work_package_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("work_packages.id",ondelete="CASCADE"),index=True); code: Mapped[str]=mapped_column(String(32)); title: Mapped[str]=mapped_column(String(200)); due_date: Mapped[date]=mapped_column(Date); status: Mapped[str]=mapped_column(String(24),default="planned"); baseline_id: Mapped[uuid.UUID|None]=mapped_column(PGUUID(as_uuid=True),ForeignKey("configuration_baselines.id")); eco_id: Mapped[uuid.UUID|None]=mapped_column(PGUUID(as_uuid=True))
class Milestone(Base):
    __tablename__="milestones"; id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); program_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("programs.id",ondelete="CASCADE"),index=True); name: Mapped[str]=mapped_column(String(160)); due_date: Mapped[date]=mapped_column(Date); status: Mapped[str]=mapped_column(String(24),default="planned")
