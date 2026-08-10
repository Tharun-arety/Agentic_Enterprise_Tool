from __future__ import annotations
import uuid
from pydantic import BaseModel, Field
class ReceiptLotIn(BaseModel):
    po_line_id: uuid.UUID; supplier_lot: str=Field(min_length=1,max_length=64); internal_lot: str=Field(min_length=1,max_length=64); quantity: float=Field(gt=0); accepted_quantity: float=Field(ge=0); certificate_ref: str|None=None
class ReceiptIn(BaseModel):
    purchase_order_id: uuid.UUID; receipt_number: str=Field(min_length=1,max_length=32); lots: list[ReceiptLotIn]=Field(min_length=1)
class ReceiptOut(BaseModel):
    id: uuid.UUID; receipt_number: str; lot_count: int
