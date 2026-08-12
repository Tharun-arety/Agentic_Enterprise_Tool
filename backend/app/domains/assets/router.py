"""Lab asset endpoints: the instrument register, calibration and rig bookings.

The reads live in `queries.py`, shared with the agent tools.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.assets import queries
from app.domains.assets.service import book
from app.domains.identity.models import Role
from app.tools.registry import ToolError

router = APIRouter(prefix="/api/assets", tags=["assets"])
auth = Depends(require_roles(Role.ENGINEER, Role.QUALITY))


class BookingIn(BaseModel):
    asset_id: str
    starts_at: datetime
    ends_at: datetime
    purpose: str


@router.get("")
async def assets(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_assets(session)


@router.get("/calibration")
async def calibration(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_calibration(session)


@router.post("/bookings")
async def create(
    payload: BookingIn,
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    try:
        booking = await book(
            session,
            uuid.UUID(payload.asset_id),
            payload.starts_at,
            payload.ends_at,
            principal.user_id,
            payload.purpose,
        )
    except ToolError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "id": str(booking.id),
        "starts_at": booking.starts_at,
        "ends_at": booking.ends_at,
        "purpose": booking.purpose,
        "status": booking.status,
    }


@router.get("/bookings")
async def bookings(
    principal: Annotated[Principal, auth],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await queries.list_bookings(session)
