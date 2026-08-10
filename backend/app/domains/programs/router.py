from typing import Annotated
from fastapi import APIRouter,Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.domains.programs.models import Deliverable,Milestone,Program,TrlGate,WorkPackage
router=APIRouter(prefix="/api/programs",tags=["programs"]); auth=Depends(require_roles(Role.ENGINEER,Role.SYSTEMS_ENGINEERING,Role.CONTROLLER))
def d(x): return {c.name:getattr(x,c.name) for c in x.__table__.columns}
@router.get("")
async def programs(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [d(x) for x in (await session.execute(select(Program))).scalars()]
@router.get("/work-packages")
async def packages(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [d(x) for x in (await session.execute(select(WorkPackage))).scalars()]
@router.get("/trl")
async def trl(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [d(x) for x in (await session.execute(select(TrlGate))).scalars()]
@router.get("/deliverables")
async def deliverables(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [d(x) for x in (await session.execute(select(Deliverable))).scalars()]
