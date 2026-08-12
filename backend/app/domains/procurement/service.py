from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.backoffice.integration import enqueue
from app.domains.procurement.models import GoodsReceipt, PurchaseOrder, PurchaseOrderLine, ReceiptLot, StockPosition
from app.domains.procurement.schemas import ReceiptIn
from app.domains.qms.models import Unit, UnitComponent
from app.domains.pdm.models import Part
from app.tools.registry import ToolError
async def receive(session:AsyncSession,payload:ReceiptIn,user_id=None):
    po=await session.get(PurchaseOrder,payload.purchase_order_id)
    if not po: raise ToolError("Purchase order does not exist.")
    if (await session.execute(select(GoodsReceipt).where(GoodsReceipt.receipt_number==payload.receipt_number))).scalar_one_or_none(): raise ToolError("Receipt number already exists.")
    receipt=GoodsReceipt(receipt_number=payload.receipt_number,purchase_order_id=po.id,received_by=user_id); session.add(receipt); await session.flush()
    for item in payload.lots:
        line=await session.get(PurchaseOrderLine,item.po_line_id)
        if not line or line.purchase_order_id!=po.id: raise ToolError("Receipt lot references a line outside the purchase order.")
        if item.accepted_quantity>item.quantity: raise ToolError("Accepted quantity cannot exceed received quantity.")
        lot=ReceiptLot(receipt_id=receipt.id,po_line_id=line.id,supplier_id=po.supplier_id,part_id=line.part_id,internal_lot=item.internal_lot,supplier_lot=item.supplier_lot,quantity=item.quantity,accepted_quantity=item.accepted_quantity,certificate_ref=item.certificate_ref,status="accepted" if item.accepted_quantity==item.quantity else "quarantine"); session.add(lot); line.received_quantity=float(line.received_quantity)+item.quantity
        stock=(await session.execute(select(StockPosition).where(StockPosition.part_id==line.part_id,StockPosition.warehouse=="Main"))).scalar_one_or_none()
        if not stock: stock=StockPosition(part_id=line.part_id,warehouse="Main"); session.add(stock)
        stock.on_hand=float(stock.on_hand)+item.accepted_quantity
    await enqueue(session,"procurement.receipt",str(receipt.id),{"receipt_number":receipt.receipt_number,"purchase_order_id":str(po.id)},f"receipt:{receipt.id}"); await session.commit(); return receipt
async def supply_risk(session:AsyncSession):
    """On-hand cover against the reorder level, worst exposure first.

    The description and lead time travel with the row on purpose: a shortfall
    on a 90-day neodymium array is a different conversation from a shortfall on
    a stock O-ring, and sorting by lead time is how a buyer decides which one
    to chase this morning.
    """
    rows=(await session.execute(select(StockPosition,Part).join(Part,Part.id==StockPosition.part_id))).all()
    risks=[{"part_number":p.part_number,"description":p.description,"on_hand":float(s.on_hand),"allocated":float(s.allocated),"available":float(s.on_hand)-float(s.allocated),"reorder_level":float(s.reorder_level),"low_stock":float(s.on_hand)-float(s.allocated)<float(s.reorder_level),"lead_time_days":p.lead_time_days,"make_or_buy":p.make_or_buy} for s,p in rows]
    return sorted(risks,key=lambda r:(not r["low_stock"],-(r["lead_time_days"] or 0),r["part_number"]))
async def affected_units(session:AsyncSession,lot_number:str):
    rows=(await session.execute(select(Unit.serial_number,Part.part_number).join(UnitComponent,UnitComponent.unit_id==Unit.id).join(Part,Part.id==UnitComponent.part_id).where((UnitComponent.lot_number==lot_number)|(UnitComponent.supplier_lot==lot_number)).distinct())).all(); return [{"serial_number":s,"part_number":p} for s,p in rows]
