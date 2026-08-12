"""Programme endpoints: work packages, TRL gates and consortium deliverables.

The reads live in `queries.py` because the agent tools serve the same data and
a second copy is how the two answers drifted apart.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.domains.programs import queries

router = APIRouter(prefix="/api/programs", tags=["programs"])
auth = Depends(require_roles(Role.ENGINEER, Role.SYSTEMS_ENGINEERING, Role.CONTROLLER))


@router.get("")
async def programmes(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_programmes(session)


@router.get("/work-packages")
async def packages(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_work_packages(session)


@router.get("/trl")
async def trl(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_trl_gates(session)


@router.get("/deliverables")
async def deliverables(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_deliverables(session)
