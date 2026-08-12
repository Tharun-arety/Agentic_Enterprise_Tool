"""Engineering change endpoints.

The role gates differ per action because the authorities differ: anyone with an
engineering role may raise a request, only a board seat may vote on one, and
only systems engineering may release the order that results.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import current_principal, require_roles
from app.core.principal import Principal
from app.domains.ecm import service
from app.domains.ecm.release import release_change_order
from app.domains.ecm.schemas import (
    ChangeOrderCreate,
    ChangeOrderOut,
    ChangeRequestCreate,
    ChangeRequestOut,
    ImpactAssessmentOut,
    ReleaseResult,
    ReviewSubmission,
)
from app.domains.identity.models import CCB_ROLES, Role
from app.tools.registry import ToolError

router = APIRouter(prefix="/api/ecm", tags=["ecm"])


def _http(exc: ToolError) -> HTTPException:
    """Map a refusal to the right status.

    A workflow guard ("cannot become approved from draft") is a conflict with
    the record's current state, not a malformed request and not a missing one.
    """
    message = str(exc)
    if message.startswith("No change"):
        code = status.HTTP_404_NOT_FOUND
    elif any(
        phrase in message
        for phrase in ("cannot become", "is not open", "already", "cannot be released")
    ):
        code = status.HTTP_409_CONFLICT
    elif "does not hold" in message or "holds no" in message:
        code = status.HTTP_403_FORBIDDEN
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=message)


@router.get("/requests", response_model=list[ChangeRequestOut])
async def list_requests(
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    priority: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ChangeRequestOut]:
    try:
        return await service.list_change_requests(
            session, status=status_filter, priority=priority, limit=limit
        )
    except ToolError as exc:
        raise _http(exc) from exc


@router.get("/requests/{number}", response_model=ChangeRequestOut)
async def read_request(
    number: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> ChangeRequestOut:
    try:
        return await service.get_change_request(session, number)
    except ToolError as exc:
        raise _http(exc) from exc


@router.post("/requests", response_model=ChangeRequestOut, status_code=201)
async def create_request(
    payload: ChangeRequestCreate,
    principal: Annotated[Principal, Depends(require_roles(Role.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChangeRequestOut:
    try:
        return await service.create_change_request(
            session,
            actor=principal,
            title=payload.title,
            problem_statement=payload.problem_statement,
            proposed_solution=payload.proposed_solution,
            affected_part_numbers=payload.affected_part_numbers,
            origin=payload.origin,
            priority=payload.priority,
            preliminary_impact=payload.preliminary_impact,
        )
    except ToolError as exc:
        raise _http(exc) from exc


@router.post("/requests/{number}/submit", response_model=ChangeRequestOut)
async def submit_request(
    number: str,
    principal: Annotated[Principal, Depends(require_roles(Role.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChangeRequestOut:
    try:
        return await service.submit_change_request(
            session, actor=principal, number=number
        )
    except ToolError as exc:
        raise _http(exc) from exc


@router.post("/requests/{number}/review", response_model=ChangeRequestOut)
async def review_request(
    number: str,
    payload: ReviewSubmission,
    principal: Annotated[Principal, Depends(require_roles(*CCB_ROLES))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChangeRequestOut:
    """Cast one board seat's vote. The request settles when the board completes."""
    try:
        return await service.record_review(
            session,
            actor=principal,
            number=number,
            decision=payload.decision,
            comment=payload.comment,
            seat=payload.seat,
        )
    except ToolError as exc:
        raise _http(exc) from exc


@router.post("/requests/{number}/reassess", response_model=ImpactAssessmentOut)
async def reassess_request(
    number: str,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ImpactAssessmentOut:
    try:
        return await service.reassess(session, actor=principal, number=number)
    except ToolError as exc:
        raise _http(exc) from exc


@router.get("/orders/{number}", response_model=ChangeOrderOut)
async def read_order(
    number: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> ChangeOrderOut:
    try:
        return await service.get_change_order(session, number)
    except ToolError as exc:
        raise _http(exc) from exc


@router.post("/orders", response_model=ChangeOrderOut, status_code=201)
async def create_order(
    payload: ChangeOrderCreate,
    principal: Annotated[
        Principal, Depends(require_roles(Role.SYSTEMS_ENGINEERING))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChangeOrderOut:
    try:
        return await service.create_change_order(
            session,
            actor=principal,
            change_request_number=payload.change_request_number,
            title=payload.title,
            disposition=payload.disposition,
            lines=payload.lines,
            effectivity_type=payload.effectivity_type,
            effective_date=payload.effective_date,
            effective_serial=payload.effective_serial,
        )
    except ToolError as exc:
        raise _http(exc) from exc


@router.post("/orders/{number}/release", response_model=ReleaseResult)
async def release_order(
    number: str,
    principal: Annotated[
        Principal, Depends(require_roles(Role.SYSTEMS_ENGINEERING))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReleaseResult:
    """Move the released configuration. One transaction; see ecm/release.py."""
    try:
        return await release_change_order(session, actor=principal, number=number)
    except ToolError as exc:
        raise _http(exc) from exc
