"""Customer reads, shared by the REST router and the agent tools."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.crm.models import (
    CustomerSite,
    DeployedUnit,
    FieldEvent,
    Lead,
    Opportunity,
)
from app.domains.pdm.models import Part
from app.domains.qms.models import Unit


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


async def list_leads(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (await session.execute(select(Lead).order_by(Lead.company))).scalars().all()
    return [
        {"name": lead.name, "company": lead.company, "status": lead.status} for lead in rows
    ]


async def list_opportunities(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(select(Opportunity).order_by(Opportunity.expected_close))
    ).scalars().all()
    return [
        {
            "id": str(opportunity.id),
            "title": opportunity.title,
            "customer_name": opportunity.customer_name,
            "stage": opportunity.stage,
            "value": float(opportunity.value),
            "currency": opportunity.currency,
            "expected_close": opportunity.expected_close,
        }
        for opportunity in rows
    ]


async def list_deployed_units(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(DeployedUnit, Unit, Part.part_number, CustomerSite)
            .join(Unit, Unit.id == DeployedUnit.unit_id)
            .join(Part, Part.id == Unit.part_id)
            .join(CustomerSite, CustomerSite.id == DeployedUnit.customer_site_id)
            .order_by(CustomerSite.customer_name, Unit.serial_number)
        )
    ).all()
    return [
        {
            "serial_number": unit.serial_number,
            "part_number": part_number,
            "unit_status": _enum_value(unit.status),
            "customer_name": site.customer_name,
            "site_name": site.site_name,
            "address": site.address,
            "commissioned_at": deployment.commissioned_at,
            "status": deployment.status,
        }
        for deployment, unit, part_number, site in rows
    ]


async def list_field_history(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(FieldEvent, Unit.serial_number, CustomerSite.customer_name)
            .join(DeployedUnit, DeployedUnit.id == FieldEvent.deployed_unit_id)
            .join(Unit, Unit.id == DeployedUnit.unit_id)
            .join(CustomerSite, CustomerSite.id == DeployedUnit.customer_site_id)
            .order_by(FieldEvent.occurred_at.desc())
        )
    ).all()
    return [
        {
            "id": str(event.id),
            "serial_number": serial_number,
            "customer_name": customer_name,
            "occurred_at": event.occurred_at,
            "event_type": event.event_type,
            "summary": event.summary,
            "resolution": event.resolution,
        }
        for event, serial_number, customer_name in rows
    ]
