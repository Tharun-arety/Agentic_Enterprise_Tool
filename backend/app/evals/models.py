from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import Boolean,DateTime,Integer,Numeric,String,Text,func
from sqlalchemy.dialects.postgresql import JSONB,UUID as PGUUID
from sqlalchemy.orm import Mapped,mapped_column
from app.core.db import Base
class EvalRun(Base):
    __tablename__="eval_runs"; id:Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); suite:Mapped[str]=mapped_column(String(64)); status:Mapped[str]=mapped_column(String(24),default="running"); passed:Mapped[int]=mapped_column(Integer,default=0); failed:Mapped[int]=mapped_column(Integer,default=0); metrics:Mapped[dict[str,Any]]=mapped_column(JSONB,default=dict); started_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now()); finished_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
class EvalCaseResult(Base):
    __tablename__="eval_case_results"; id:Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); run_id:Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),index=True); case_name:Mapped[str]=mapped_column(String(128)); category:Mapped[str]=mapped_column(String(48),index=True); passed:Mapped[bool]=mapped_column(Boolean); score:Mapped[float]=mapped_column(Numeric(8,4)); latency_ms:Mapped[int]=mapped_column(Integer); detail:Mapped[str|None]=mapped_column(Text); trajectory:Mapped[list]=mapped_column(JSONB,default=list)
