from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import DateTime,String,func
from sqlalchemy.dialects.postgresql import JSONB,UUID as PGUUID
from sqlalchemy.orm import Mapped,mapped_column
from app.core.db import Base
class AutomationFinding(Base):
    __tablename__="automation_findings"; id:Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4); idempotency_key:Mapped[str]=mapped_column(String(160),unique=True); detector:Mapped[str]=mapped_column(String(64),index=True); severity:Mapped[str]=mapped_column(String(16)); title:Mapped[str]=mapped_column(String(256)); evidence:Mapped[dict[str,Any]]=mapped_column(JSONB); status:Mapped[str]=mapped_column(String(24),default="open",index=True); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
