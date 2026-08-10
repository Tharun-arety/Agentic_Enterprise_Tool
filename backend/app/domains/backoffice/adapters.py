from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, TypeVar
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import get_settings
from app.domains.backoffice.dto import *  # canonical DTO surface
from app.domains.backoffice.port import BackofficePort
from app.domains.pdm.models import Part

T = TypeVar("T")


class LocalBackofficeAdapter(BackofficePort):
    def __init__(self, session: AsyncSession): self.session = session
    async def capabilities(self): return AdapterCapabilities(read=("items","suppliers","purchase_orders","receipts","stock","customers","opportunities","projects","tasks","timesheets","assets","maintenance","cost_centres","budgets","commitments","actuals"), write=("items",), webhooks=True)
    async def health(self): return AdapterHealth(adapter="local", status="ok")
    async def list_items(self):
        rows = (await self.session.execute(select(Part).order_by(Part.part_number))).scalars().all()
        return [ItemDTO(external_id=str(p.id), item_code=p.part_number, name=p.name, standard_cost=Decimal(str(p.standard_cost or 0)), currency=p.currency) for p in rows]
    async def upsert_item(self, item):
        row = (await self.session.execute(select(Part).where(Part.part_number == item.item_code))).scalar_one_or_none()
        if row is None: row = Part(part_number=item.item_code, name=item.name); self.session.add(row)
        row.name, row.standard_cost, row.currency = item.name, item.standard_cost, item.currency
        await self.session.commit(); item.external_id = str(row.id); return item
    async def _empty(self): return []
    list_suppliers = list_purchase_orders = list_receipts = list_stock = list_customers = list_opportunities = list_projects = list_tasks = list_timesheets = list_assets = list_maintenance = list_cost_centres = list_budgets = list_commitments = list_actuals = _empty


class ErpnextBackofficeAdapter(BackofficePort):
    RESOURCE = {"items":("Item",ItemDTO),"suppliers":("Supplier",SupplierDTO),"purchase_orders":("Purchase Order",PurchaseOrderDTO),"receipts":("Purchase Receipt",ReceiptDTO),"stock":("Bin",StockDTO),"customers":("Customer",CustomerDTO),"opportunities":("Opportunity",OpportunityDTO),"projects":("Project",ProjectDTO),"tasks":("Task",TaskDTO),"timesheets":("Timesheet",TimesheetDTO),"assets":("Asset",AssetDTO),"maintenance":("Asset Maintenance",MaintenanceDTO),"cost_centres":("Cost Center",CostCentreDTO),"budgets":("Budget",BudgetDTO),"commitments":("Purchase Invoice",CommitmentDTO),"actuals":("GL Entry",ActualDTO)}
    def __init__(self, client: httpx.AsyncClient | None = None):
        s=get_settings(); self.base=s.erpnext_base_url.rstrip("/"); self.client=client or httpx.AsyncClient(timeout=s.tool_timeout_seconds, headers={"Authorization":f"token {s.erpnext_api_key}:{s.erpnext_api_secret}"})
    async def capabilities(self): return AdapterCapabilities(read=tuple(self.RESOURCE), write=("items",), webhooks=True)
    async def health(self):
        try: r=await self.client.get(f"{self.base}/api/method/ping"); r.raise_for_status(); return AdapterHealth(adapter="erpnext",status="ok")
        except Exception as exc: return AdapterHealth(adapter="erpnext",status="down",detail=str(exc)[:240])
    async def _list(self, key):
        resource, cls=self.RESOURCE[key]; r=await self.client.get(f"{self.base}/api/resource/{resource}",params={"limit_page_length":100}); r.raise_for_status()
        return [cls.model_validate(_normalise_erp(key,x)) for x in r.json().get("data",[])]
    async def upsert_item(self,item):
        payload={"item_code":item.item_code,"item_name":item.name,"standard_rate":str(item.standard_cost),"stock_uom":"Nos"}; r=await self.client.put(f"{self.base}/api/resource/Item/{item.item_code}",json=payload)
        if r.status_code==404: r=await self.client.post(f"{self.base}/api/resource/Item",json=payload)
        r.raise_for_status(); item.external_id=r.json().get("data",{}).get("name",item.item_code); return item
    async def list_items(self): return await self._list("items")
    async def list_suppliers(self): return await self._list("suppliers")
    async def list_purchase_orders(self): return await self._list("purchase_orders")
    async def list_receipts(self): return await self._list("receipts")
    async def list_stock(self): return await self._list("stock")
    async def list_customers(self): return await self._list("customers")
    async def list_opportunities(self): return await self._list("opportunities")
    async def list_projects(self): return await self._list("projects")
    async def list_tasks(self): return await self._list("tasks")
    async def list_timesheets(self): return await self._list("timesheets")
    async def list_assets(self): return await self._list("assets")
    async def list_maintenance(self): return await self._list("maintenance")
    async def list_cost_centres(self): return await self._list("cost_centres")
    async def list_budgets(self): return await self._list("budgets")
    async def list_commitments(self): return await self._list("commitments")
    async def list_actuals(self): return await self._list("actuals")


def _normalise_erp(key: str, x: dict[str,Any]) -> dict[str,Any]:
    # ERPNext field names differ by DocType; keep the anti-corruption mapping here.
    base={"external_id":str(x.get("name") or x.get("item_code") or "unknown"),"modified_at":x.get("modified")}
    maps={"items":{"item_code":x.get("item_code") or x.get("name"),"name":x.get("item_name") or x.get("name"),"standard_cost":x.get("standard_rate",0),"currency":"EUR"},"suppliers":{"name":x.get("supplier_name") or x.get("name"),"lead_time_days":x.get("lead_time_days")}}
    return base | maps.get(key, x)
