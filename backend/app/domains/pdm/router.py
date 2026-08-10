"""PDM read endpoints.

Thin: each one resolves arguments and delegates to the same service function the
agent tools call, so the dashboard and the agent cannot disagree about what a
BOM contains.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import current_principal
from app.core.filestore import FileStoreError
from app.core.principal import Principal
from app.domains.pdm import baselines as baseline_service
from app.domains.pdm import documents as document_service
from app.domains.pdm.models import BomType
from app.domains.pdm.schemas import (
    BaselineDiff,
    BaselineOut,
    BomResponse,
    ComplianceRollup,
    DocumentOut,
    PartDetail,
    WhereUsedResponse,
)
from app.domains.pdm.service import (
    get_bom_structure,
    get_compliance_rollup,
    get_part_detail,
    get_where_used,
)
from app.tools.registry import ToolError

router = APIRouter(prefix="/api", tags=["pdm"])

BomTypeQuery = Annotated[BomType, Query(description="EBOM (as designed) or MBOM (as built).")]
AsOfQuery = Annotated[date | None, Query(description="Effectivity date; defaults to today.")]


def _not_found(exc: ToolError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/parts/{part_number}", response_model=PartDetail)
async def read_part(
    part_number: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> PartDetail:
    try:
        return await get_part_detail(session, part_number)
    except ToolError as exc:
        raise _not_found(exc) from exc


@router.get("/parts/{part_number}/bom", response_model=BomResponse)
async def read_bom(
    part_number: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    bom_type: BomTypeQuery = BomType.EBOM,
    as_of: AsOfQuery = None,
) -> BomResponse:
    try:
        return await get_bom_structure(
            session, part_number, bom_type=bom_type.value, as_of=as_of
        )
    except ToolError as exc:
        raise _not_found(exc) from exc


@router.get("/parts/{part_number}/where-used", response_model=WhereUsedResponse)
async def read_where_used(
    part_number: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    bom_type: BomTypeQuery = BomType.EBOM,
    as_of: AsOfQuery = None,
) -> WhereUsedResponse:
    try:
        return await get_where_used(
            session, part_number, bom_type=bom_type.value, as_of=as_of
        )
    except ToolError as exc:
        raise _not_found(exc) from exc


@router.get("/parts/{part_number}/compliance", response_model=ComplianceRollup)
async def read_compliance(
    part_number: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    bom_type: BomTypeQuery = BomType.EBOM,
    as_of: AsOfQuery = None,
) -> ComplianceRollup:
    try:
        return await get_compliance_rollup(
            session, part_number, bom_type=bom_type.value, as_of=as_of
        )
    except ToolError as exc:
        raise _not_found(exc) from exc


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------


@router.get("/baselines", response_model=list[BaselineOut])
async def list_baselines(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[BaselineOut]:
    return await baseline_service.list_baselines(session)


@router.get("/baselines/diff", response_model=BaselineDiff)
async def read_baseline_diff(
    session: Annotated[AsyncSession, Depends(get_session)],
    from_baseline: Annotated[str, Query(description="Name of the earlier baseline.")],
    to_baseline: Annotated[str, Query(description="Name of the later baseline.")],
) -> BaselineDiff:
    try:
        return await baseline_service.diff_baselines(session, from_baseline, to_baseline)
    except ToolError as exc:
        # A mismatched pair of baselines is a bad request, not a missing one.
        code = (
            status.HTTP_400_BAD_REQUEST
            if "Comparing" in str(exc)
            else status.HTTP_404_NOT_FOUND
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    session: Annotated[AsyncSession, Depends(get_session)],
    part_number: Annotated[str | None, Query()] = None,
) -> list[DocumentOut]:
    try:
        return await document_service.list_documents(session, part_number=part_number)
    except ToolError as exc:
        raise _not_found(exc) from exc


@router.post("/documents/{document_number}/checkout", response_model=DocumentOut)
async def checkout_document(
    document_number: str,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentOut:
    try:
        return await document_service.check_out(
            session, actor=principal, document_number=document_number
        )
    except ToolError as exc:
        code = (
            status.HTTP_409_CONFLICT
            if "checked out" in str(exc)
            else status.HTTP_404_NOT_FOUND
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get("/documents/{document_number}/content")
async def download_document(
    document_number: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    revision: Annotated[str | None, Query(description="Defaults to the latest.")] = None,
) -> Response:
    try:
        chosen, data = await document_service.fetch_content(
            session, document_number=document_number, revision=revision
        )
    except ToolError as exc:
        # A failed integrity check is a server-side problem, not a client one.
        code = (
            status.HTTP_500_INTERNAL_SERVER_ERROR
            if "integrity check" in str(exc)
            else status.HTTP_404_NOT_FOUND
        )
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except FileStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    return Response(
        content=data,
        media_type=chosen.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{chosen.filename}"',
            # The hash the content was approved under, so a caller can verify
            # what they received without a second round trip.
            "X-Content-SHA256": chosen.content_hash,
            "X-Document-Revision": chosen.revision,
        },
    )
