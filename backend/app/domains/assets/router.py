from datetime import datetime,timezone
from typing import Annotated
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.domains.assets.models import AssetBooking,CalibrationCertificate,LabAsset
from app.domains.assets.service import book
from app.tools.registry import ToolError
router=APIRouter(prefix="/api/assets",tags=["assets"]); auth=Depends(require_roles(Role.ENGINEER,Role.QUALITY))
class BookingIn(BaseModel): asset_id:str; starts_at:datetime; ends_at:datetime; purpose:str
def d(x): return {c.name:getattr(x,c.name) for c in x.__table__.columns}
@router.get("")
async def assets(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [d(x) for x in (await session.execute(select(LabAsset))).scalars()]
@router.get("/calibration")
async def calibration(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]):
    today=datetime.now(timezone.utc).date(); return [{**d(x),"overdue":x.valid_until<today,"due_soon":today<=x.valid_until<today.replace(day=today.day)+__import__("datetime").timedelta(days=30)} for x in (await session.execute(select(CalibrationCertificate))).scalars()]
@router.post("/bookings")
async def create(payload:BookingIn,principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]):
    try: return d(await book(session,__import__("uuid").UUID(payload.asset_id),payload.starts_at,payload.ends_at,principal.user_id,payload.purpose))
    except ToolError as exc: raise HTTPException(409,str(exc)) from exc
@router.get("/bookings")
async def bookings(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [d(x) for x in (await session.execute(select(AssetBooking).order_by(AssetBooking.starts_at))).scalars()]
