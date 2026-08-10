from typing import Annotated
from fastapi import APIRouter,Depends
from sqlalchemy import func,select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.domains.resources.models import EngineerCapacity,ResourceAllocation,TimesheetEntry
router=APIRouter(prefix="/api/resources",tags=["resources"]); auth=Depends(require_roles(Role.ENGINEER,Role.CONTROLLER,Role.MANUFACTURING))
@router.get("/capacity")
async def capacity(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]):
    rows=(await session.execute(select(EngineerCapacity.user_id,EngineerCapacity.week_start,EngineerCapacity.available_hours,func.coalesce(func.sum(ResourceAllocation.allocated_hours),0)).outerjoin(ResourceAllocation,(ResourceAllocation.user_id==EngineerCapacity.user_id)&(ResourceAllocation.week_start==EngineerCapacity.week_start)).group_by(EngineerCapacity.id))).all(); return [{"user_id":str(u),"week_start":w,"available_hours":float(a),"allocated_hours":float(x),"remaining_hours":float(a)-float(x),"overloaded":float(x)>float(a)} for u,w,a,x in rows]
@router.get("/timesheets")
async def timesheets(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [{c.name:getattr(x,c.name) for c in x.__table__.columns} for x in (await session.execute(select(TimesheetEntry))).scalars()]
