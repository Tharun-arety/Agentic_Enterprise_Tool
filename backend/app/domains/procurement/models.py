from __future__ import annotations
import uuid
from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.db import Base


class Supplier(Base):
    __tablename__="suppliers"
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    code: Mapped[str]=mapped_column(String(32),unique=True,index=True)
    name: Mapped[str]=mapped_column(String(160))
    lead_time_days: Mapped[int]=mapped_column(Integer,default=30)
    quality_rating: Mapped[float]=mapped_column(Numeric(5,2),default=100)
    external_id: Mapped[str|None]=mapped_column(String(128),index=True)


class PurchaseOrder(Base):
    __tablename__="purchase_orders"
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    order_number: Mapped[str]=mapped_column(String(32),unique=True,index=True)
    supplier_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("suppliers.id"),index=True)
    status: Mapped[str]=mapped_column(String(24),default="open",index=True)
    ordered_at: Mapped[date]=mapped_column(Date,default=date.today)
    required_date: Mapped[date|None]=mapped_column(Date)
    currency: Mapped[str]=mapped_column(String(3),default="EUR")
    external_id: Mapped[str|None]=mapped_column(String(128),index=True)


class PurchaseOrderLine(Base):
    __tablename__="purchase_order_lines"
    __table_args__=(UniqueConstraint("purchase_order_id","line_number",name="uq_po_line"),)
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    purchase_order_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("purchase_orders.id",ondelete="CASCADE"),index=True)
    line_number: Mapped[int]=mapped_column(Integer)
    part_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("parts.id"),index=True)
    quantity: Mapped[float]=mapped_column(Numeric(14,4))
    received_quantity: Mapped[float]=mapped_column(Numeric(14,4),default=0)
    unit_price: Mapped[float]=mapped_column(Numeric(14,4),default=0)


class GoodsReceipt(Base):
    __tablename__="goods_receipts"
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    receipt_number: Mapped[str]=mapped_column(String(32),unique=True,index=True)
    purchase_order_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("purchase_orders.id"),index=True)
    received_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    received_by: Mapped[uuid.UUID|None]=mapped_column(PGUUID(as_uuid=True))
    external_id: Mapped[str|None]=mapped_column(String(128),index=True)


class ReceiptLot(Base):
    __tablename__="receipt_lots"
    __table_args__=(UniqueConstraint("supplier_id","supplier_lot",name="uq_supplier_lot"),)
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    receipt_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("goods_receipts.id",ondelete="CASCADE"),index=True)
    po_line_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("purchase_order_lines.id"),index=True)
    supplier_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("suppliers.id"),index=True)
    part_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("parts.id"),index=True)
    internal_lot: Mapped[str]=mapped_column(String(64),unique=True,index=True)
    supplier_lot: Mapped[str]=mapped_column(String(64),index=True)
    quantity: Mapped[float]=mapped_column(Numeric(14,4))
    accepted_quantity: Mapped[float]=mapped_column(Numeric(14,4))
    certificate_ref: Mapped[str|None]=mapped_column(String(128))
    status: Mapped[str]=mapped_column(String(24),default="accepted",index=True)


class StockPosition(Base):
    __tablename__="stock_positions"
    __table_args__=(UniqueConstraint("part_id","warehouse",name="uq_stock_position"),)
    id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    part_id: Mapped[uuid.UUID]=mapped_column(PGUUID(as_uuid=True),ForeignKey("parts.id"),index=True)
    warehouse: Mapped[str]=mapped_column(String(64),default="Main")
    on_hand: Mapped[float]=mapped_column(Numeric(14,4),default=0)
    allocated: Mapped[float]=mapped_column(Numeric(14,4),default=0)
    reorder_level: Mapped[float]=mapped_column(Numeric(14,4),default=0)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())
