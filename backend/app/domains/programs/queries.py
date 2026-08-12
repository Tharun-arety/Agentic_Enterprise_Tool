"""Programme reads, shared by the REST router and the agent tools.

These used to be written twice — once inline in the router and once in
`enterprise_tools`. The two copies drifted: the router learned to resolve work
package and programme names while the tool kept dumping raw columns, so the
screens showed "WP4 — ECLIPSE field validation" and the agent answered with
`work_package c6cd00e3-2d04-42d8-a26a-777217ac95cb`. One function per read, and
the divergence cannot happen again.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.identity.models import User
from app.domains.programs.models import (
    ConsortiumPartner,
    Deliverable,
    Milestone,
    Program,
    TrlGate,
    WorkPackage,
)


async def list_programmes(session: AsyncSession) -> list[dict[str, Any]]:
    programmes = (await session.execute(select(Program).order_by(Program.code))).scalars().all()
    packages = (await session.execute(select(WorkPackage))).scalars().all()
    partners = (await session.execute(select(ConsortiumPartner))).scalars().all()
    milestones = (
        await session.execute(select(Milestone).order_by(Milestone.due_date))
    ).scalars().all()

    return [
        {
            "code": programme.code,
            "name": programme.name,
            "status": programme.status,
            "work_package_count": sum(1 for p in packages if p.program_id == programme.id),
            "partners": [
                {"name": partner.name, "role": partner.role}
                for partner in partners
                if partner.program_id == programme.id
            ],
            "milestones": [
                {
                    "name": milestone.name,
                    "due_date": milestone.due_date,
                    "status": milestone.status,
                }
                for milestone in milestones
                if milestone.program_id == programme.id
            ],
        }
        for programme in programmes
    ]


async def list_work_packages(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(WorkPackage, Program.code, Program.name)
            .join(Program, Program.id == WorkPackage.program_id)
            .order_by(Program.code, WorkPackage.code)
        )
    ).all()
    return [
        {
            "code": package.code,
            "title": package.title,
            # Name only: the code travels in its own field, and joining the two
            # here produced "HYLICAL — HyLICAL — cryogenic hydrogen liquefaction"
            # wherever a programme name already opened with its own code.
            "programme": program_name,
            "programme_code": program_code,
            "budget": float(package.budget),
            "trl_target": package.trl_target,
        }
        for package, program_code, program_name in rows
    ]


async def list_trl_gates(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(TrlGate, WorkPackage, Program.code, User.full_name)
            .join(WorkPackage, WorkPackage.id == TrlGate.work_package_id)
            .join(Program, Program.id == WorkPackage.program_id)
            .outerjoin(User, User.id == TrlGate.approved_by)
            .order_by(Program.code, WorkPackage.code, TrlGate.trl)
        )
    ).all()
    return [
        {
            "id": str(gate.id),
            "work_package": f"{package.code} — {package.title}",
            "programme": program_code,
            "trl": gate.trl,
            "trl_target": package.trl_target,
            "status": gate.status,
            "evidence": gate.evidence,
            "approved_by": approver,
        }
        for gate, package, program_code, approver in rows
    ]


async def list_deliverables(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Deliverable, WorkPackage.code, Program.code)
            .join(WorkPackage, WorkPackage.id == Deliverable.work_package_id)
            .join(Program, Program.id == WorkPackage.program_id)
            .order_by(Deliverable.due_date)
        )
    ).all()
    return [
        {
            "code": deliverable.code,
            "title": deliverable.title,
            "work_package": package_code,
            "programme": program_code,
            "due_date": deliverable.due_date,
            "status": deliverable.status,
        }
        for deliverable, package_code, program_code in rows
    ]
