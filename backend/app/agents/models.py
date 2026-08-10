from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base
class AgentRun(Base):
    __tablename__="agent_runs"
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    correlation_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),index=True,default=uuid.uuid4)
    user_id: Mapped[uuid.UUID|None]=mapped_column(PGUUID(as_uuid=True),ForeignKey("users.id"),index=True)
    status: Mapped[str]=mapped_column(String(24),default="running",index=True)
    question: Mapped[str]=mapped_column(Text)
    routed_domains: Mapped[list]=mapped_column(JSONB,default=list)
    model_snapshot: Mapped[str]=mapped_column(String(96))
    prompt_version: Mapped[str]=mapped_column(String(32),default="2026-08-10.v1")
    input_tokens: Mapped[int]=mapped_column(Integer,default=0); output_tokens: Mapped[int]=mapped_column(Integer,default=0)
    estimated_cost_usd: Mapped[float]=mapped_column(Numeric(12,6),default=0)
    outcome: Mapped[dict[str,Any]|None]=mapped_column(JSONB)
    started_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now()); finished_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); duration_ms: Mapped[int|None]=mapped_column(Integer)
class ToolInvocation(Base):
    __tablename__="tool_invocations"
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    run_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("agent_runs.id",ondelete="CASCADE"),index=True)
    domain: Mapped[str]=mapped_column(String(32),index=True); tool_name: Mapped[str]=mapped_column(String(96),index=True); arguments: Mapped[dict[str,Any]]=mapped_column(JSONB); result: Mapped[dict[str,Any]]=mapped_column(JSONB); status: Mapped[str]=mapped_column(String(24)); duration_ms: Mapped[int]=mapped_column(Integer); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
