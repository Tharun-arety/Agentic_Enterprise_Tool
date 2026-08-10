"""Endpoints for the approval inbox and the audit trail."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEvent
from app.core.db import get_session
from app.core.deps import current_principal
from app.core.principal import Principal
from app.core.proposals import (
    AgentProposal,
    ProposalError,
    ProposalStatus,
    decide,
)
from app.core.schemas import AuditEventOut, ProposalDecision, ProposalOut

router = APIRouter(prefix="/api", tags=["governance"])


@router.get("/proposals", response_model=list[ProposalOut])
async def list_proposals(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[
        ProposalStatus | None,
        Query(alias="status", description="Omit to see every proposal."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ProposalOut]:
    """The approval inbox: what agents have prepared and nobody has ruled on."""
    query = select(AgentProposal).order_by(AgentProposal.created_at.desc()).limit(limit)
    if status_filter is not None:
        query = query.where(AgentProposal.status == status_filter)
    rows = (await session.execute(query)).scalars().all()
    return [ProposalOut.model_validate(row) for row in rows]


@router.get("/proposals/{proposal_id}", response_model=ProposalOut)
async def read_proposal(
    proposal_id: uuid.UUID,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProposalOut:
    proposal = await session.get(AgentProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"No proposal {proposal_id}.")
    return ProposalOut.model_validate(proposal)


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalOut)
async def approve_proposal(
    proposal_id: uuid.UUID,
    payload: ProposalDecision,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProposalOut:
    """Approve and apply. The role check lives on the proposal, not the route.

    Each proposal names the role required to approve it, taken from the tool
    that produced it — so authority travels with the operation instead of being
    duplicated as a decorator every new endpoint has to remember.
    """
    return await _decide(session, proposal_id, principal, approve=True, note=payload.note)


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
async def reject_proposal(
    proposal_id: uuid.UUID,
    payload: ProposalDecision,
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProposalOut:
    return await _decide(session, proposal_id, principal, approve=False, note=payload.note)


async def _decide(
    session: AsyncSession,
    proposal_id: uuid.UUID,
    principal: Principal,
    *,
    approve: bool,
    note: str | None,
) -> ProposalOut:
    try:
        proposal = await decide(
            session,
            proposal_id=proposal_id,
            reviewer=principal,
            approve=approve,
            note=note,
        )
    except ProposalError as exc:
        message = str(exc)
        # "requires the X role" is an authorisation failure; the rest are
        # conflicts with the proposal's current state.
        code = (
            status.HTTP_403_FORBIDDEN
            if "role" in message
            else status.HTTP_409_CONFLICT
        )
        if message.startswith("No proposal"):
            code = status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=message) from exc
    return ProposalOut.model_validate(proposal)


@router.get("/audit", response_model=list[AuditEventOut])
async def read_audit(
    principal: Annotated[Principal, Depends(current_principal)],
    session: Annotated[AsyncSession, Depends(get_session)],
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[str | None, Query()] = None,
    correlation_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEventOut]:
    """Configuration status accounting: what happened, to what, by whom."""
    query = select(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(limit)
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditEvent.entity_id == entity_id)
    if correlation_id:
        query = query.where(AuditEvent.correlation_id == correlation_id)
    rows = (await session.execute(query)).scalars().all()
    return [AuditEventOut.model_validate(row) for row in rows]
