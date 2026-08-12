from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.domains.pdm.models import Part
from app.domains.procurement.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.domains.procurement.schemas import ReceiptIn, ReceiptOut
from app.domains.procurement.service import affected_units, receive, supply_risk
from app.tools.registry import ToolError
router=APIRouter(prefix="/api/procurement",tags=["procurement"]); auth=Depends(require_roles(Role.PROCUREMENT,Role.QUALITY,Role.MANUFACTURING))
@router.get("/suppliers")
async def suppliers(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return [{"id":str(x.id),"code":x.code,"name":x.name,"lead_time_days":x.lead_time_days,"quality_rating":float(x.quality_rating)} for x in (await session.execute(select(Supplier).order_by(Supplier.code))).scalars()]
@router.get("/purchase-orders")
async def orders(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]):
    """Open orders with the supplier named and the money on them totalled."""
    rows=(await session.execute(select(PurchaseOrder,Supplier).join(Supplier,Supplier.id==PurchaseOrder.supplier_id).order_by(PurchaseOrder.ordered_at.desc()))).all()
    lines=(await session.execute(select(PurchaseOrderLine,Part.part_number).join(Part,Part.id==PurchaseOrderLine.part_id))).all()
    by_order:dict[str,list]=  {}
    for line,part_number in lines: by_order.setdefault(str(line.purchase_order_id),[]).append((line,part_number))
    return [{
        "order_number":order.order_number,"supplier":supplier.name,"supplier_code":supplier.code,
        "status":order.status,"ordered_at":order.ordered_at,"required_date":order.required_date,"currency":order.currency,
        "value":sum(float(l.quantity)*float(l.unit_price) for l,_ in by_order.get(str(order.id),[])),
        "lines":[{"line_number":l.line_number,"part_number":pn,"quantity":float(l.quantity),"received_quantity":float(l.received_quantity),"unit_price":float(l.unit_price)} for l,pn in sorted(by_order.get(str(order.id),[]),key=lambda x:x[0].line_number)],
    } for order,supplier in rows]
@router.post("/receipts",response_model=ReceiptOut)
async def create_receipt(payload:ReceiptIn,principal:Annotated[Principal,Depends(require_roles(Role.PROCUREMENT))],session:Annotated[AsyncSession,Depends(get_session)]):
    try: row=await receive(session,payload,principal.user_id); return ReceiptOut(id=row.id,receipt_number=row.receipt_number,lot_count=len(payload.lots))
    except ToolError as exc: raise HTTPException(409,str(exc)) from exc
@router.get("/stock-risk")
async def risk(principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return await supply_risk(session)
@router.get("/lots/{lot_number}/affected-units")
async def trace(lot_number:str,principal:Annotated[Principal,auth],session:Annotated[AsyncSession,Depends(get_session)]): return await affected_units(session,lot_number)
