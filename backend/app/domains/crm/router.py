from typing import Annotated
from fastapi import APIRouter,Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.domains.crm.models import CustomerSite,DeployedUnit,FieldEvent,Lead,Opportunity
router=APIRouter(prefix="/api/crm",tags=["crm"]); auth=Depends(require_roles(Role.ENGINEER,Role.ADMIN))
def d(x): return {c.name:getattr(x,c.name) for c in x.__table__.columns}
@router.get("/leads")
async def leads(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [d(x) for x in (await session.execute(select(Lead))).scalars()]
@router.get("/opportunities")
async def opportunities(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [d(x) for x in (await session.execute(select(Opportunity))).scalars()]
@router.get("/deployed-units")
async def deployed(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [d(x) for x in (await session.execute(select(DeployedUnit))).scalars()]
@router.get("/field-history")
async def history(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [d(x) for x in (await session.execute(select(FieldEvent).order_by(FieldEvent.occurred_at.desc()))).scalars()]
