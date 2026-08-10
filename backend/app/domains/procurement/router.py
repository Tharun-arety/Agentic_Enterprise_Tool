from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.domains.procurement.models import GoodsReceipt, PurchaseOrder, Supplier
from app.domains.procurement.schemas import ReceiptIn, ReceiptOut
from app.domains.procurement.service import affected_units, receive, supply_risk
from app.tools.registry import ToolError
router=APIRouter(prefix="/api/procurement",tags=["procurement"]); auth=Depends(require_roles(Role.PROCUREMENT,Role.QUALITY,Role.MANUFACTURING))
@router.get("/suppliers")
async def suppliers(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [{"id":str(x.id),"code":x.code,"name":x.name,"lead_time_days":x.lead_time_days,"quality_rating":float(x.quality_rating)} for x in (await session.execute(select(Supplier).order_by(Supplier.code))).scalars()]
@router.get("/purchase-orders")
async def orders(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [{"id":str(x.id),"order_number":x.order_number,"status":x.status,"required_date":x.required_date} for x in (await session.execute(select(PurchaseOrder).order_by(PurchaseOrder.ordered_at.desc()))).scalars()]
@router.post("/receipts",response_model=ReceiptOut)
async def create_receipt(payload:ReceiptIn,principal:Annotated[Principal,Depends(require_roles(Role.PROCUREMENT))],session:Annotated[AsyncSession,Depends(get_session)]):
    try: row=await receive(session,payload,principal.user_id); return ReceiptOut(id=row.id,receipt_number=row.receipt_number,lot_count=len(payload.lots))
    except ToolError as exc: raise HTTPException(409,str(exc)) from exc
@router.get("/stock-risk")
async def risk(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return await supply_risk(session)
@router.get("/lots/{lot_number}/affected-units")
async def trace(lot_number:str,principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return await affected_units(session,lot_number)
