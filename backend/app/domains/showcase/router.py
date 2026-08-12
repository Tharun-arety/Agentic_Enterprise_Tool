from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import current_principal
from app.core.principal import Principal
from app.core.proposals import AgentProposal, ProposalStatus
from app.domains.controlling.models import CostRollupSnapshot
from app.domains.ecm.models import ChangeBoardReview, ChangeOrder, ChangeRequest
from app.domains.knowledge.models import SourceDocumentVersion
from app.domains.pdm.models import Part
from app.domains.procurement.models import GoodsReceipt, ReceiptLot, StockPosition
from app.domains.qms.models import LabTestRecord, NonConformance, TestResult, Unit

router = APIRouter(prefix="/api/showcase", tags=["showcase"])


class ShowcaseCounts(BaseModel):
    controlled_parts: int
    built_units: int
    test_samples: int
    failed_samples: int
    open_ncrs: int
    low_stock_items: int
    indexed_documents: int
    pending_proposals: int


class ShowcaseStep(BaseModel):
    domain: str
    title: str
    reference: str
    detail: str
    status: str
    href: str


class ShowcaseResponse(BaseModel):
    generated_at: datetime
    product: str = "ECLIPSE 1 kW Retail Chiller"
    product_number: str = "ECL-SYS-1000"
    counts: ShowcaseCounts
    workflow: list[ShowcaseStep]


_cache: tuple[float, ShowcaseResponse] | None = None
_cache_lock = asyncio.Lock()
_CACHE_SECONDS = 20


async def _build(session: AsyncSession) -> ShowcaseResponse:
    failed_unit = (
        select(Unit.serial_number)
        .join(LabTestRecord, LabTestRecord.unit_id == Unit.id)
        .where(LabTestRecord.result == TestResult.FAIL)
        .order_by(Unit.serial_number)
        .limit(1)
        .scalar_subquery()
    )
    latest_ecr_id = (
        select(ChangeRequest.id)
        .order_by(ChangeRequest.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    statement = select(
        select(func.count(Part.id)).scalar_subquery().label("controlled_parts"),
        select(func.count(Unit.id)).scalar_subquery().label("built_units"),
        select(func.count(LabTestRecord.id)).scalar_subquery().label("test_samples"),
        select(func.count(LabTestRecord.id))
        .where(LabTestRecord.result == TestResult.FAIL)
        .scalar_subquery()
        .label("failed_samples"),
        select(func.count(NonConformance.id))
        .where(NonConformance.closed_at.is_(None))
        .scalar_subquery()
        .label("open_ncrs"),
        select(func.count(StockPosition.id))
        .where(StockPosition.on_hand - StockPosition.allocated < StockPosition.reorder_level)
        .scalar_subquery()
        .label("low_stock_items"),
        select(func.count(SourceDocumentVersion.id))
        .where(SourceDocumentVersion.extraction_status == "indexed")
        .scalar_subquery()
        .label("indexed_documents"),
        select(func.count(AgentProposal.id))
        .where(AgentProposal.status == ProposalStatus.PENDING)
        .scalar_subquery()
        .label("pending_proposals"),
        select(GoodsReceipt.receipt_number)
        .join(ReceiptLot, ReceiptLot.receipt_id == GoodsReceipt.id)
        .join(NonConformance, NonConformance.lot_number == ReceiptLot.internal_lot)
        .order_by(NonConformance.raised_at.desc())
        .limit(1)
        .scalar_subquery()
        .label("receipt"),
        select(NonConformance.lot_number)
        .order_by(NonConformance.raised_at.desc())
        .limit(1)
        .scalar_subquery()
        .label("lot"),
        failed_unit.label("failed_unit"),
        select(NonConformance.number)
        .order_by(NonConformance.raised_at.desc())
        .limit(1)
        .scalar_subquery()
        .label("ncr"),
        select(NonConformance.status)
        .order_by(NonConformance.raised_at.desc())
        .limit(1)
        .scalar_subquery()
        .label("ncr_status"),
        select(ChangeRequest.number)
        .order_by(ChangeRequest.created_at.desc())
        .limit(1)
        .scalar_subquery()
        .label("ecr"),
        select(ChangeRequest.status)
        .order_by(ChangeRequest.created_at.desc())
        .limit(1)
        .scalar_subquery()
        .label("ecr_status"),
        select(func.count(ChangeBoardReview.id))
        .where(ChangeBoardReview.change_request_id == latest_ecr_id)
        .scalar_subquery()
        .label("ccb_votes"),
        select(ChangeOrder.number)
        .order_by(ChangeOrder.released_at.desc().nullslast(), ChangeOrder.created_at.desc())
        .limit(1)
        .scalar_subquery()
        .label("eco"),
        select(ChangeOrder.status)
        .order_by(ChangeOrder.released_at.desc().nullslast(), ChangeOrder.created_at.desc())
        .limit(1)
        .scalar_subquery()
        .label("eco_status"),
        select(CostRollupSnapshot.total_cost)
        .order_by(CostRollupSnapshot.captured_at.desc())
        .limit(1)
        .scalar_subquery()
        .label("after_cost"),
        select(CostRollupSnapshot.total_cost)
        .order_by(CostRollupSnapshot.captured_at.desc())
        .offset(1)
        .limit(1)
        .scalar_subquery()
        .label("before_cost"),
        select(SourceDocumentVersion.filename)
        .where(SourceDocumentVersion.extraction_status == "indexed")
        .order_by(SourceDocumentVersion.uploaded_at.desc())
        .limit(1)
        .scalar_subquery()
        .label("ecn"),
    )
    row = (await session.execute(statement)).one()._mapping
    receipt = row["receipt"] or "No receipt"
    lot = row["lot"] or "No lot"
    serial = row["failed_unit"] or "No affected unit"
    ncr = row["ncr"] or "No NCR"
    ecr = row["ecr"] or "No ECR"
    eco = row["eco"] or "No released ECO"
    ecn = row["ecn"] or "No indexed ECN"
    votes = int(row["ccb_votes"] or 0)
    before_cost = float(row["before_cost"] or 0)
    after_cost = float(row["after_cost"] or 0)
    cost_delta = after_cost - before_cost

    def enum_text(value: object) -> str:
        return str(getattr(value, "value", value) or "unknown")

    return ShowcaseResponse(
        generated_at=datetime.now(timezone.utc),
        counts=ShowcaseCounts(
            controlled_parts=int(row["controlled_parts"] or 0),
            built_units=int(row["built_units"] or 0),
            test_samples=int(row["test_samples"] or 0),
            failed_samples=int(row["failed_samples"] or 0),
            open_ncrs=int(row["open_ncrs"] or 0),
            low_stock_items=int(row["low_stock_items"] or 0),
            indexed_documents=int(row["indexed_documents"] or 0),
            pending_proposals=int(row["pending_proposals"] or 0),
        ),
        workflow=[
            ShowcaseStep(domain="Procurement", title="Supplier receipt captured", reference=receipt, detail="Rhine Magnetics GmbH · PO-2026-0042", status="Received", href="/procurement"),
            ShowcaseStep(domain="Genealogy", title="Material lot traced into build", reference=lot, detail=f"Affected unit {serial}", status="Traceable", href="/qms"),
            ShowcaseStep(domain="Quality", title="Acceptance test breached", reference=serial, detail=f"{int(row['failed_samples'] or 0)} samples below the 15.0 K limit", status="Failed", href="/qms"),
            ShowcaseStep(domain="QMS", title="Lot-scoped non-conformance", reference=ncr, detail=f"Status: {enum_text(row['ncr_status'])}", status="Escalated", href="/qms"),
            ShowcaseStep(domain="ECM", title="ECR impact assessment generated", reference=ecr, detail="Affected product, units, documents, revalidation and cost exposure frozen for review", status=enum_text(row["ecr_status"]), href="/ecm"),
            ShowcaseStep(domain="CCB", title="Cross-functional approval complete", reference=ecr, detail=f"{votes} of 4 board seats approved the corrective configuration", status="Approved", href="/ecm"),
            ShowcaseStep(domain="ECO / Controlling", title="ECO released, MBOM rebuilt and repriced", reference=eco, detail=f"{enum_text(row['eco_status'])} · EUR {before_cost:,.2f} → {after_cost:,.2f} ({cost_delta:+,.2f})", status="Released", href="/controlling"),
            ShowcaseStep(domain="Knowledge", title="Released change evidence indexed", reference=ecn, detail="Controlled revision and exact citation available to hybrid search", status="Searchable", href="/knowledge"),
        ],
    )


@router.get("", response_model=ShowcaseResponse)
async def showcase(
    _principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ShowcaseResponse:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    async with _cache_lock:
        now = time.monotonic()
        if _cache is None or now - _cache[0] >= _CACHE_SECONDS:
            _cache = (now, await _build(session))
        return _cache[1]
