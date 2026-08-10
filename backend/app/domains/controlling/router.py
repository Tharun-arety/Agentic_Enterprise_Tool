from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.domains.controlling.schemas import CostRollup, SnapshotOut, VarianceRow
from app.domains.controlling.service import capture_snapshot, rollup_cost, variance_report
router=APIRouter(prefix="/api/controlling",tags=["controlling"])
auth=Depends(require_roles(Role.CONTROLLER,Role.ENGINEER,Role.MANUFACTURING))
@router.get("/rollup/{part_number}",response_model=CostRollup)
async def rollup(part_number:str,principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)],batch_size:Annotated[float,Query(gt=0)]=1): return await rollup_cost(session,part_number,batch_size)
@router.post("/rollup/{part_number}/snapshots",response_model=SnapshotOut)
async def snapshot(part_number:str,principal:Annotated[Principal,Depends(require_roles(Role.CONTROLLER))],session:Annotated[AsyncSession,Depends(get_session)],batch_size:Annotated[float,Query(gt=0)]=1):
    row=await capture_snapshot(session,part_number,batch_size,captured_by=principal.user_id); return SnapshotOut(id=row.id,total_cost=float(row.total_cost))
@router.get("/variance",response_model=list[VarianceRow])
async def variance(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)],fiscal_year:int): return await variance_report(session,fiscal_year)
