"""Non-conformance, disposition, and escalation into an engineering change.

Two things here are worth more than the CRUD around them.

**A lot-scoped non-conformance knows what it reached.** Raise one against a
batch of material and the affected units are resolved from the build records,
not typed in by whoever happened to remember. That is the difference between
containment and hope.

**Escalation closes the loop.** Some problems are a bad batch; some are a bad
design. `escalate_to_change_request` turns the second kind into an ECR carrying
the non-conformance's evidence, and records the link both ways. Without it
quality and engineering keep separate lists that stop referring to each other.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import audit
from app.core.audit import AuditAction
from app.core.principal import Principal
from app.domains.ecm.models import ChangeOrigin, ChangePriority, ChangeRequest
from app.domains.ecm.service import _next_number, create_change_request
from app.domains.pdm.models import Part
from app.domains.qms.models import (
    CapaAction,
    CapaKind,
    Disposition,
    NcrSeverity,
    NcrSource,
    NcrStatus,
    NonConformance,
    Unit,
)
from app.domains.qms.queries import LOT_TRACE, MAX_GENEALOGY_DEPTH
from app.domains.qms.schemas import CapaActionOut, NonConformanceOut
from app.tools.registry import ToolError

logger = logging.getLogger(__name__)

# Once a disposition is set the material has been dealt with; reopening it
# would leave two contradictory instructions on the shop floor.
_CLOSED_STATES = {NcrStatus.CLOSED}


async def _load(session: AsyncSession, number: str) -> NonConformance:
    ncr = (
        await session.execute(
            select(NonConformance)
            .where(NonConformance.number == number.strip().upper())
            .options(selectinload(NonConformance.actions))
        )
    ).scalar_one_or_none()
    if ncr is None:
        known = (
            await session.execute(
                select(NonConformance.number).order_by(NonConformance.number)
            )
        ).scalars().all()
        raise ToolError(
            f"No non-conformance {number!r}. Known: {', '.join(known)}"
            if known
            else f"No non-conformance {number!r}, and none have been raised."
        )
    return ncr


async def _to_out(session: AsyncSession, ncr: NonConformance) -> NonConformanceOut:
    serial = None
    if ncr.unit_id is not None:
        serial = (
            await session.execute(
                select(Unit.serial_number).where(Unit.id == ncr.unit_id)
            )
        ).scalar_one_or_none()
    part_number = None
    if ncr.part_id is not None:
        part_number = (
            await session.execute(select(Part.part_number).where(Part.id == ncr.part_id))
        ).scalar_one_or_none()
    ecr_number = None
    if ncr.escalated_ecr_id is not None:
        ecr_number = (
            await session.execute(
                select(ChangeRequest.number).where(
                    ChangeRequest.id == ncr.escalated_ecr_id
                )
            )
        ).scalar_one_or_none()

    return NonConformanceOut(
        id=ncr.id,
        number=ncr.number,
        title=ncr.title,
        description=ncr.description,
        source=ncr.source,
        severity=ncr.severity,
        status=ncr.status,
        disposition=ncr.disposition,
        disposition_note=ncr.disposition_note,
        serial_number=serial,
        part_number=part_number,
        lot_number=ncr.lot_number,
        raised_by_label=ncr.raised_by_label,
        raised_at=ncr.raised_at,
        closed_at=ncr.closed_at,
        escalated_ecr_number=ecr_number,
        affected_units=await _affected_units(session, ncr),
        actions=[CapaActionOut.model_validate(action) for action in ncr.actions],
    )


async def _affected_units(session: AsyncSession, ncr: NonConformance) -> list[str]:
    """Everything the problem reached, resolved from the build records."""
    if ncr.lot_number:
        rows = (
            await session.execute(
                LOT_TRACE,
                {"lot_number": ncr.lot_number, "max_depth": MAX_GENEALOGY_DEPTH},
            )
        ).mappings().all()
        return [row["serial_number"] for row in rows]
    if ncr.unit_id is not None:
        serial = (
            await session.execute(
                select(Unit.serial_number).where(Unit.id == ncr.unit_id)
            )
        ).scalar_one_or_none()
        return [serial] if serial else []
    return []


async def raise_non_conformance(
    session: AsyncSession,
    *,
    actor: Principal,
    title: str,
    description: str,
    source: NcrSource,
    severity: NcrSeverity = NcrSeverity.MINOR,
    serial_number: str | None = None,
    part_number: str | None = None,
    lot_number: str | None = None,
    commit: bool = True,
) -> NonConformanceOut:
    if not any([serial_number, part_number, lot_number]):
        raise ToolError(
            "A non-conformance has to be against something: give a serial "
            "number, a part number, or a lot number."
        )

    unit_id = None
    if serial_number:
        unit_id = (
            await session.execute(
                select(Unit.id).where(Unit.serial_number == serial_number.strip().upper())
            )
        ).scalar_one_or_none()
        if unit_id is None:
            raise ToolError(f"No unit with serial {serial_number!r}.")

    part_id = None
    if part_number:
        part_id = (
            await session.execute(
                select(Part.id).where(Part.part_number == part_number.strip().upper())
            )
        ).scalar_one_or_none()
        if part_id is None:
            raise ToolError(f"No part named {part_number!r}.")

    now = datetime.now(timezone.utc)
    ncr = NonConformance(
        number=await _next_number(session, NonConformance, "NCR", now),
        title=title.strip(),
        description=description.strip(),
        source=source,
        severity=severity,
        status=NcrStatus.OPEN,
        unit_id=unit_id,
        part_id=part_id,
        lot_number=lot_number.strip() if lot_number else None,
        raised_by=actor.user_id,
        raised_by_label=actor.label,
    )
    session.add(ncr)
    await session.flush()

    audit.record(
        session,
        actor=actor,
        action=AuditAction.CREATE,
        entity_type="NonConformance",
        entity_id=ncr.id,
        after={
            "number": ncr.number,
            "title": ncr.title,
            "severity": severity.value,
            "scope": serial_number or part_number or lot_number,
        },
    )
    if commit:
        await session.commit()

    logger.info("Raised %s (%s)", ncr.number, severity.value)
    return await _to_out(session, await _load(session, ncr.number))


async def set_disposition(
    session: AsyncSession,
    *,
    actor: Principal,
    number: str,
    disposition: Disposition,
    note: str | None = None,
    commit: bool = True,
) -> NonConformanceOut:
    ncr = await _load(session, number)
    if ncr.status in _CLOSED_STATES:
        raise ToolError(
            f"{ncr.number} is closed. Its disposition stands; raise a new "
            "non-conformance if the material needs handling differently."
        )
    if disposition is Disposition.PENDING:
        raise ToolError("'Pending' is the absence of a disposition, not one.")
    if disposition in (Disposition.USE_AS_IS, Disposition.SCRAP) and not note:
        raise ToolError(
            f"{disposition.value} needs a written justification: it is the "
            "decision an auditor will ask about."
        )

    before = ncr.disposition
    ncr.disposition = disposition
    ncr.disposition_note = note
    ncr.status = NcrStatus.DISPOSITIONED

    audit.record(
        session,
        actor=actor,
        action=AuditAction.UPDATE,
        entity_type="NonConformance",
        entity_id=ncr.id,
        before={"disposition": before.value},
        after={"disposition": disposition.value, "status": ncr.status.value},
        reason=note,
    )
    if commit:
        await session.commit()
    return await _to_out(session, ncr)


async def add_action(
    session: AsyncSession,
    *,
    actor: Principal,
    number: str,
    kind: CapaKind,
    description: str,
    owner_label: str | None = None,
    due_date=None,
    commit: bool = True,
) -> NonConformanceOut:
    ncr = await _load(session, number)
    action = CapaAction(
        non_conformance_id=ncr.id,
        kind=kind,
        description=description.strip(),
        owner_label=owner_label,
        due_date=due_date,
    )
    session.add(action)
    await session.flush()
    audit.record(
        session,
        actor=actor,
        action=AuditAction.CREATE,
        entity_type="CapaAction",
        entity_id=action.id,
        after={"ncr": ncr.number, "kind": kind.value, "description": description},
    )
    if commit:
        await session.commit()
    return await _to_out(session, await _load(session, ncr.number))


async def close_non_conformance(
    session: AsyncSession, *, actor: Principal, number: str, commit: bool = True
) -> NonConformanceOut:
    ncr = await _load(session, number)
    if ncr.status is NcrStatus.CLOSED:
        raise ToolError(f"{ncr.number} is already closed.")
    if ncr.disposition is Disposition.PENDING:
        raise ToolError(
            f"{ncr.number} has no disposition. Closing it would leave the "
            "affected material with no instruction against it."
        )
    incomplete = [a for a in ncr.actions if a.completed_at is None]
    if incomplete:
        raise ToolError(
            f"{ncr.number} has {len(incomplete)} outstanding action(s). Complete "
            "them, or remove the ones that turned out not to be needed."
        )

    ncr.status = NcrStatus.CLOSED
    ncr.closed_at = datetime.now(timezone.utc)
    audit.record(
        session,
        actor=actor,
        action=AuditAction.TRANSITION,
        entity_type="NonConformance",
        entity_id=ncr.id,
        after={"status": NcrStatus.CLOSED.value},
    )
    if commit:
        await session.commit()
    return await _to_out(session, ncr)


async def escalate_to_change_request(
    session: AsyncSession,
    *,
    actor: Principal,
    number: str,
    proposed_solution: str,
    commit: bool = True,
) -> NonConformanceOut:
    """Turn a non-conformance into an engineering change request.

    Used when the finding is a design problem rather than a one-off escape. The
    request carries the non-conformance's evidence — what was found, on which
    units — so the board is not asked to rule on a summary of a summary.
    """
    ncr = await _load(session, number)
    if ncr.escalated_ecr_id is not None:
        existing = (
            await session.execute(
                select(ChangeRequest.number).where(
                    ChangeRequest.id == ncr.escalated_ecr_id
                )
            )
        ).scalar_one_or_none()
        raise ToolError(f"{ncr.number} has already been escalated as {existing}.")

    affected = await _resolve_affected_parts(session, ncr)
    if not affected:
        raise ToolError(
            f"{ncr.number} names no part, and none could be derived from its "
            "scope, so there is nothing for a change request to be about."
        )

    units = await _affected_units(session, ncr)
    evidence = (
        f"Raised as {ncr.number} ({ncr.severity.value.lower()}, found at "
        f"{ncr.source.value.lower()}): {ncr.description}"
    )
    if units:
        evidence += f" Units affected: {', '.join(units)}."
    if ncr.lot_number:
        evidence += f" Material lot: {ncr.lot_number}."

    request = await create_change_request(
        session,
        actor=actor,
        title=f"{ncr.title} (from {ncr.number})",
        problem_statement=evidence,
        proposed_solution=proposed_solution.strip(),
        affected_part_numbers=affected,
        origin=(
            ChangeOrigin.FIELD if ncr.source is NcrSource.FIELD else ChangeOrigin.QUALITY
        ),
        priority=(
            ChangePriority.URGENT
            if ncr.severity is NcrSeverity.CRITICAL
            else ChangePriority.HIGH
        ),
        commit=False,
    )

    ncr.escalated_ecr_id = request.id
    audit.record(
        session,
        actor=actor,
        action=AuditAction.UPDATE,
        entity_type="NonConformance",
        entity_id=ncr.id,
        after={"escalated_to": request.number},
        reason="Escalated to engineering change.",
    )
    if commit:
        await session.commit()

    logger.info("Escalated %s to %s", ncr.number, request.number)
    return await _to_out(session, await _load(session, ncr.number))


async def _resolve_affected_parts(
    session: AsyncSession, ncr: NonConformance
) -> list[str]:
    """Which part numbers a change request out of this NCR should name."""
    if ncr.part_id is not None:
        number = (
            await session.execute(select(Part.part_number).where(Part.id == ncr.part_id))
        ).scalar_one_or_none()
        return [number] if number else []
    if ncr.unit_id is not None:
        # The unit's own part: the article that failed is the thing to change.
        number = (
            await session.execute(
                select(Part.part_number)
                .join(Unit, Unit.part_id == Part.id)
                .where(Unit.id == ncr.unit_id)
            )
        ).scalar_one_or_none()
        return [number] if number else []
    if ncr.lot_number:
        # A lot belongs to a component; find which one from the build records.
        from app.domains.qms.models import UnitComponent

        numbers = (
            await session.execute(
                select(Part.part_number)
                .join(UnitComponent, UnitComponent.part_id == Part.id)
                .where(UnitComponent.lot_number == ncr.lot_number)
                .distinct()
            )
        ).scalars().all()
        return sorted(numbers)
    return []


async def list_non_conformances(
    session: AsyncSession, status: str | None = None, limit: int = 50
) -> list[NonConformanceOut]:
    query = (
        select(NonConformance)
        .order_by(NonConformance.raised_at.desc())
        .limit(limit)
        .options(selectinload(NonConformance.actions))
    )
    if status:
        try:
            query = query.where(NonConformance.status == NcrStatus(status))
        except ValueError:
            options = ", ".join(state.value for state in NcrStatus)
            raise ToolError(f"Unknown status {status!r}. One of: {options}") from None
    rows = (await session.execute(query)).scalars().all()
    return [await _to_out(session, row) for row in rows]


async def get_non_conformance(session: AsyncSession, number: str) -> NonConformanceOut:
    return await _to_out(session, await _load(session, number))
