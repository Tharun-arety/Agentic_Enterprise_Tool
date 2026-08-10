"""Canonical contracts at the Magnotherm/back-office boundary."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from pydantic import BaseModel, Field


class CanonicalDTO(BaseModel):
    external_id: str
    modified_at: datetime | None = None


class ItemDTO(CanonicalDTO):
    item_code: str
    name: str
    standard_cost: Decimal = Decimal("0")
    currency: str = "EUR"


class SupplierDTO(CanonicalDTO):
    name: str
    lead_time_days: int | None = None


class PurchaseOrderDTO(CanonicalDTO):
    supplier_id: str
    status: str
    required_date: date | None = None
    total: Decimal = Decimal("0")
    currency: str = "EUR"


class ReceiptDTO(CanonicalDTO):
    purchase_order_id: str
    received_at: datetime
    lots: list[dict[str, Any]] = Field(default_factory=list)


class StockDTO(CanonicalDTO):
    item_code: str
    warehouse: str
    actual_qty: Decimal
    reorder_level: Decimal = Decimal("0")


class CustomerDTO(CanonicalDTO):
    name: str
    site: str | None = None


class OpportunityDTO(CanonicalDTO):
    customer_id: str
    title: str
    status: str
    value: Decimal = Decimal("0")
    currency: str = "EUR"


class ProjectDTO(CanonicalDTO):
    name: str
    status: str


class TaskDTO(CanonicalDTO):
    project_id: str
    subject: str
    status: str


class TimesheetDTO(CanonicalDTO):
    employee: str
    project_id: str | None = None
    hours: Decimal
    posting_date: date


class AssetDTO(CanonicalDTO):
    asset_name: str
    status: str
    location: str | None = None


class MaintenanceDTO(CanonicalDTO):
    asset_id: str
    due_date: date
    status: str


class CostCentreDTO(CanonicalDTO):
    name: str


class BudgetDTO(CanonicalDTO):
    cost_centre_id: str
    amount: Decimal
    currency: str = "EUR"


class CommitmentDTO(CanonicalDTO):
    cost_centre_id: str
    amount: Decimal
    currency: str = "EUR"


class ActualDTO(CanonicalDTO):
    cost_centre_id: str
    amount: Decimal
    currency: str = "EUR"


class AdapterCapabilities(BaseModel):
    read: tuple[str, ...]
    write: tuple[str, ...]
    webhooks: bool = False


class AdapterHealth(BaseModel):
    adapter: Literal["local", "erpnext"]
    status: Literal["ok", "degraded", "down"]
    last_sync_at: datetime | None = None
    queue_depth: int = 0
    detail: str | None = None
