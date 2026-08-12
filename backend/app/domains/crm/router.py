"""Customer endpoints: pipeline, sites, deployed units and field history.

A deployed unit reaches through to the serial it actually is, so an account
view lands on the same article the quality screens hold test evidence for. That
link is the reason this domain sits next to engineering rather than in a
separate sales tool.

The reads live in `queries.py`, shared with the agent tools.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.crm import queries
from app.domains.identity.models import Role

router = APIRouter(prefix="/api/crm", tags=["crm"])
auth = Depends(require_roles(Role.ENGINEER, Role.ADMIN))


@router.get("/leads")
async def leads(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_leads(session)


@router.get("/opportunities")
async def opportunities(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_opportunities(session)


@router.get("/deployed-units")
async def deployed(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_deployed_units(session)


@router.get("/field-history")
async def history(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_field_history(session)
