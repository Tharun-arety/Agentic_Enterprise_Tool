"""Resource endpoints: weekly engineer capacity and booked time.

The reads live in `queries.py`, shared with the agent tools.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.domains.resources import queries

router = APIRouter(prefix="/api/resources", tags=["resources"])
auth = Depends(require_roles(Role.ENGINEER, Role.CONTROLLER, Role.MANUFACTURING))


@router.get("/capacity")
async def capacity(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_capacity(session)


@router.get("/timesheets")
async def timesheets(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_timesheets(session)
