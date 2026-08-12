"""Quality endpoints: units, genealogy, lot traces, non-conformances."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.domains.pdm.models import Part, PartRevision
from app.domains.qms import ncr as ncr_service
from app.domains.qms.models import LabTestRecord, TestResult, Unit
from app.domains.qms.schemas import (
    DispositionRequest,
    LotTrace,
    NonConformanceCreate,
    NonConformanceOut,
    QmsResponse,
    UnitGenealogy,
)
from app.domains.qms.service import (
    get_unit_genealogy,
    query_qms_test_metrics,
    trace_lot,
)
from app.tools.registry import ToolError

router = APIRouter(prefix="/api", tags=["qms"])


def _http(exc: ToolError) -> HTTPException:
    message = str(exc)
    if message.startswith("No "):
        code = status.HTTP_404_NOT_FOUND
    elif "already" in message or "is closed" in message:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=message)


@router.get("/units")
async def list_units(session: Annotated[AsyncSession, Depends(get_session)]):
    """Every built article, with its acceptance-test tally.

    The quality screens are all "pick a serial, then look at it", and a picker
    that cannot say which serials failed anything makes the reader open each
    one in turn to find out.
    """
    rows = (
        await session.execute(
            select(
                Unit.serial_number,
                Part.part_number,
                PartRevision.revision,
                Unit.status,
                Unit.built_at,
                Unit.plant,
                Unit.customer_ref,
                func.count(LabTestRecord.id),
                func.count(LabTestRecord.id).filter(
                    LabTestRecord.result == TestResult.FAIL
                ),
            )
            .join(Part, Part.id == Unit.part_id)
            .outerjoin(PartRevision, PartRevision.id == Unit.built_to_revision_id)
            .outerjoin(LabTestRecord, LabTestRecord.unit_id == Unit.id)
            .group_by(
                Unit.serial_number,
                Part.part_number,
                PartRevision.revision,
                Unit.status,
                Unit.built_at,
                Unit.plant,
                Unit.customer_ref,
            )
            .order_by(Unit.built_at.desc().nullslast(), Unit.serial_number)
        )
    ).all()
    return [
        {
            "serial_number": serial_number,
            "part_number": part_number,
            "built_to_revision": revision,
            "status": status_value.value if hasattr(status_value, "value") else status_value,
            "built_at": built_at,
            "plant": plant,
            "customer_ref": customer_ref,
            "sample_count": sample_count,
            "fail_count": fail_count,
        }
        for (
            serial_number,
            part_number,
            revision,
            status_value,
            built_at,
            plant,
            customer_ref,
            sample_count,
            fail_count,
        ) in rows
    ]


@router.get("/qms/{serial_number}", response_model=QmsResponse)
async def read_qms(
    serial_number: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> QmsResponse:
    try:
        return await query_qms_test_metrics(session, serial_number)
    except ToolError as exc:
        raise _http(exc) from exc


@router.get("/units/{serial_number}/genealogy", response_model=UnitGenealogy)
async def read_genealogy(
    serial_number: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> UnitGenealogy:
    """The as-built record: what this individual article actually contains."""
    try:
        return await get_unit_genealogy(session, serial_number)
    except ToolError as exc:
        raise _http(exc) from exc


@router.get("/lots/{lot_number}/trace", response_model=LotTrace)
async def read_lot_trace(
    lot_number: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> LotTrace:
    """Every unit containing a lot of material — the containment question."""
    try:
        return await trace_lot(session, lot_number)
    except ToolError as exc:
        raise _http(exc) from exc


# --------------------------------------------------------------------------
# Non-conformance
# --------------------------------------------------------------------------


@router.get("/ncrs", response_model=list[NonConformanceOut])
async def list_ncrs(
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[NonConformanceOut]:
    try:
        return await ncr_service.list_non_conformances(session, status_filter, limit)
    except ToolError as exc:
        raise _http(exc) from exc


@router.get("/ncrs/{number}", response_model=NonConformanceOut)
async def read_ncr(
    number: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> NonConformanceOut:
    try:
        return await ncr_service.get_non_conformance(session, number)
    except ToolError as exc:
        raise _http(exc) from exc


@router.post("/ncrs", response_model=NonConformanceOut, status_code=201)
async def create_ncr(
    payload: NonConformanceCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.QUALITY))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NonConformanceOut:
    try:
        return await ncr_service.raise_non_conformance(
            session,
            actor=principal,
            title=payload.title,
            description=payload.description,
            source=payload.source,
            severity=payload.severity,
            serial_number=payload.serial_number,
            part_number=payload.part_number,
            lot_number=payload.lot_number,
        )
    except ToolError as exc:
        raise _http(exc) from exc


@router.post("/ncrs/{number}/disposition", response_model=NonConformanceOut)
async def disposition_ncr(
    number: str,
    payload: DispositionRequest,
    principal: Annotated[Principal, Depends(require_roles(Role.QUALITY))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NonConformanceOut:
    try:
        return await ncr_service.set_disposition(
            session,
            actor=principal,
            number=number,
            disposition=payload.disposition,
            note=payload.note,
        )
    except ToolError as exc:
        raise _http(exc) from exc


@router.post("/ncrs/{number}/escalate", response_model=NonConformanceOut)
async def escalate_ncr(
    number: str,
    proposed_solution: Annotated[str, Query(min_length=10)],
    principal: Annotated[Principal, Depends(require_roles(Role.QUALITY))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NonConformanceOut:
    """Turn a finding into an engineering change request, carrying its evidence."""
    try:
        return await ncr_service.escalate_to_change_request(
            session,
            actor=principal,
            number=number,
            proposed_solution=proposed_solution,
        )
    except ToolError as exc:
        raise _http(exc) from exc


@router.post("/ncrs/{number}/close", response_model=NonConformanceOut)
async def close_ncr(
    number: str,
    principal: Annotated[Principal, Depends(require_roles(Role.QUALITY))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NonConformanceOut:
    try:
        return await ncr_service.close_non_conformance(
            session, actor=principal, number=number
        )
    except ToolError as exc:
        raise _http(exc) from exc
