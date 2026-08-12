"""Resource reads, shared by the REST router and the agent tools."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.identity.models import User
from app.domains.programs.models import WorkPackage
from app.domains.resources.models import (
    EngineerCapacity,
    ResourceAllocation,
    TimesheetEntry,
)


def person(full_name: str | None, email: str | None) -> str:
    """Seed users carry their function after an em dash; the name is enough."""
    if full_name:
        return full_name.split(" — ")[0]
    return email or "Unassigned"


async def list_capacity(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(
                EngineerCapacity.user_id,
                EngineerCapacity.week_start,
                EngineerCapacity.available_hours,
                func.coalesce(func.sum(ResourceAllocation.allocated_hours), 0),
                User.full_name,
                User.email,
            )
            .outerjoin(
                ResourceAllocation,
                (ResourceAllocation.user_id == EngineerCapacity.user_id)
                & (ResourceAllocation.week_start == EngineerCapacity.week_start),
            )
            .outerjoin(User, User.id == EngineerCapacity.user_id)
            .group_by(EngineerCapacity.id, User.full_name, User.email)
            .order_by(EngineerCapacity.week_start, User.full_name)
        )
    ).all()

    # Which packages the booked hours went to, so an overloaded week names its
    # cause rather than just its size.
    package_rows = (
        await session.execute(
            select(
                ResourceAllocation.user_id,
                ResourceAllocation.week_start,
                WorkPackage.code,
                ResourceAllocation.allocated_hours,
            ).join(WorkPackage, WorkPackage.id == ResourceAllocation.work_package_id)
        )
    ).all()
    packages: dict[tuple[str, str], list[dict[str, object]]] = {}
    for user_id, week_start, code, hours in package_rows:
        packages.setdefault((str(user_id), str(week_start)), []).append(
            {"work_package": code, "hours": float(hours)}
        )

    return [
        {
            "user_id": str(user_id),
            "engineer": person(full_name, email),
            "week_start": week_start,
            "available_hours": float(available),
            "allocated_hours": float(allocated),
            "remaining_hours": float(available) - float(allocated),
            "overloaded": float(allocated) > float(available),
            "packages": packages.get((str(user_id), str(week_start)), []),
        }
        for user_id, week_start, available, allocated, full_name, email in rows
    ]


async def list_timesheets(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(TimesheetEntry, User.full_name, User.email, WorkPackage.code)
            .outerjoin(User, User.id == TimesheetEntry.user_id)
            .outerjoin(WorkPackage, WorkPackage.id == TimesheetEntry.work_package_id)
            .order_by(TimesheetEntry.work_date.desc())
        )
    ).all()
    return [
        {
            "id": str(entry.id),
            "engineer": person(full_name, email),
            "work_package": package_code,
            "work_date": entry.work_date,
            "hours": float(entry.hours),
            "description": entry.description,
        }
        for entry, full_name, email, package_code in rows
    ]
