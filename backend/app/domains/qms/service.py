"""QMS services: metrics with verdicts, unit build records, traceability."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from statistics import fmean

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import audit
from app.core.audit import AuditAction
from app.core.principal import Principal
from app.domains.pdm.models import ConfigurationBaseline, Part, PartRevision
from app.domains.pdm.service import get_bom_structure, latest_revision
from app.domains.qms.metrics import METRIC_UNITS
from app.domains.qms.models import (
    LabTestRecord,
    TestProtocol,
    TestResult,
    Unit,
    UnitComponent,
    UnitStatus,
)
from app.domains.qms.queries import (
    LOT_TRACE,
    MAX_GENEALOGY_DEPTH,
    UNIT_GENEALOGY,
)
from app.domains.qms.schemas import (
    BuildResult,
    GenealogyLine,
    LabTestRecordOut,
    LotTrace,
    MetricBreach,
    MetricSummary,
    QmsResponse,
    TracedUnit,
    UnitGenealogy,
)
from app.tools.registry import ToolError

logger = logging.getLogger(__name__)


async def _load_unit(session: AsyncSession, serial_number: str) -> Unit:
    serial_number = serial_number.strip().upper()
    unit = (
        await session.execute(
            select(Unit)
            .where(Unit.serial_number == serial_number)
            .options(selectinload(Unit.test_records))
        )
    ).scalar_one_or_none()
    if unit is not None:
        return unit

    known = (
        await session.execute(select(Unit.serial_number).order_by(Unit.serial_number))
    ).scalars().all()
    raise ToolError(
        f"No unit with serial {serial_number!r}. Known serials: {', '.join(known)}"
        if known
        else f"No unit with serial {serial_number!r} and none have been built — "
        "has the database been seeded?"
    )


# --------------------------------------------------------------------------
# Acceptance
# --------------------------------------------------------------------------


def evaluate(
    record: LabTestRecord, protocol: TestProtocol | None
) -> tuple[TestResult, list[dict]]:
    """Judge one reading against a protocol's limits.

    Returns the verdict and the breaches. Called at the moment of recording;
    the outcome is then stored, because a reading was judged against the
    specification in force on the day and later tightening a limit must not
    retroactively fail a unit that met it.
    """
    if protocol is None or not protocol.limits:
        return TestResult.NOT_EVALUATED, []

    breaches: list[dict] = []
    for limit in protocol.limits:
        value = getattr(record, limit.metric, None)
        if value is None:
            continue
        below = limit.lower_limit is not None and value < limit.lower_limit
        above = limit.upper_limit is not None and value > limit.upper_limit
        if below or above:
            breaches.append(
                MetricBreach(
                    metric=limit.metric,
                    unit=METRIC_UNITS.get(limit.metric, ""),
                    value=float(value),
                    lower_limit=limit.lower_limit,
                    upper_limit=limit.upper_limit,
                ).model_dump(mode="json")
            )

    return (TestResult.FAIL if breaches else TestResult.PASS), breaches


async def resolve_protocol(
    session: AsyncSession, part_id, code: str | None = None
) -> TestProtocol | None:
    """The protocol in force for a part: named explicitly, or the active one."""
    query = select(TestProtocol).options(selectinload(TestProtocol.limits))
    if code:
        query = query.where(TestProtocol.code == code.strip().upper())
    else:
        query = query.where(
            TestProtocol.applies_to_part_id == part_id, TestProtocol.is_active.is_(True)
        )
    return (
        await session.execute(query.order_by(TestProtocol.created_at.desc()).limit(1))
    ).scalar_one_or_none()


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


async def query_qms_test_metrics(
    session: AsyncSession, serial_number: str, limit: int = 200
) -> QmsResponse:
    """The time-ordered lab test history for one physical unit."""
    unit = await _load_unit(session, serial_number)
    records = sorted(unit.test_records, key=lambda r: r.recorded_at)[:limit]

    if not records:
        raise ToolError(
            f"Unit {unit.serial_number} exists but has no lab test records yet."
        )

    part_number = (
        await session.execute(select(Part.part_number).where(Part.id == unit.part_id))
    ).scalar_one_or_none()
    revision = None
    if unit.built_to_revision_id is not None:
        revision = (
            await session.execute(
                select(PartRevision.revision).where(
                    PartRevision.id == unit.built_to_revision_id
                )
            )
        ).scalar_one_or_none()

    protocol = None
    protocol_ids = {r.protocol_id for r in records if r.protocol_id}
    if protocol_ids:
        found = (
            await session.execute(
                select(TestProtocol)
                .where(TestProtocol.id.in_(protocol_ids))
                .options(selectinload(TestProtocol.limits))
            )
        ).scalars().all()
        protocol = found[0] if found else None

    limits = {limit_.metric: limit_ for limit_ in (protocol.limits if protocol else [])}

    summaries: list[MetricSummary] = []
    for metric, unit_label in METRIC_UNITS.items():
        values = [getattr(record, metric) for record in records]
        spec = limits.get(metric)
        summaries.append(
            MetricSummary(
                metric=metric,
                unit=unit_label,
                minimum=min(values),
                maximum=max(values),
                mean=round(fmean(values), 4),
                latest=values[-1],
                lower_limit=spec.lower_limit if spec else None,
                upper_limit=spec.upper_limit if spec else None,
            )
        )

    return QmsResponse(
        serial_number=unit.serial_number,
        part_number=part_number,
        built_to_revision=revision,
        status=unit.status,
        protocol=protocol.label if protocol else None,
        sample_count=len(records),
        pass_count=sum(1 for r in records if r.result is TestResult.PASS),
        fail_count=sum(1 for r in records if r.result is TestResult.FAIL),
        records=[
            LabTestRecordOut(
                recorded_at=record.recorded_at,
                temperature_span_delta_K=record.temperature_span_delta_K,
                pressure_drop_mbar=record.pressure_drop_mbar,
                magnetization_cycles_hz=record.magnetization_cycles_hz,
                cooling_capacity_W=record.cooling_capacity_W,
                result=record.result,
                breaches=[MetricBreach.model_validate(b) for b in (record.breaches or [])],
                test_rig=record.test_rig,
                operator=record.operator,
            )
            for record in records
        ],
        summaries=summaries,
    )


# --------------------------------------------------------------------------
# Building a unit
# --------------------------------------------------------------------------


async def build_unit(
    session: AsyncSession,
    *,
    actor: Principal,
    serial_number: str,
    part_number: str,
    lots: dict[str, str] | None = None,
    plant: str | None = None,
    built_at: datetime | None = None,
    as_of: date | None = None,
    commit: bool = True,
) -> BuildResult:
    """Record what an individual article was built from.

    Snapshots the structure in force at build time into `UnitComponent` rows.
    Prefers the manufacturing view, because that is what the line actually
    consumed; falls back to the engineering view when no MBOM has been derived.

    `lots` maps part number to the lot of material used. Components with no lot
    supplied are still recorded — an incomplete build record is worth more than
    none — but they are reported as warnings, because they are the components a
    future recall will not be able to trace.
    """
    serial_number = serial_number.strip().upper()
    part_number = part_number.strip().upper()
    lots = {k.strip().upper(): v for k, v in (lots or {}).items()}

    existing = (
        await session.execute(
            select(Unit.id).where(Unit.serial_number == serial_number)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ToolError(
            f"Serial {serial_number} has already been built. A build record is "
            "written once; correct it with a non-conformance, not an overwrite."
        )

    part = (
        await session.execute(select(Part).where(Part.part_number == part_number))
    ).scalar_one_or_none()
    if part is None:
        raise ToolError(f"No part named {part_number!r} to build.")
    revision = await latest_revision(session, part)
    if revision is None:
        raise ToolError(f"{part_number} has no revision, so nothing can be built to it.")

    warnings: list[str] = []
    bom_type = "MBOM"
    try:
        bom = await get_bom_structure(session, part_number, bom_type="MBOM", as_of=as_of)
        if bom.total_nodes <= 1:
            raise ToolError("empty MBOM")
    except ToolError:
        bom = await get_bom_structure(session, part_number, bom_type="EBOM", as_of=as_of)
        bom_type = "EBOM"
        warnings.append(
            "No manufacturing BOM was available, so the build record was taken "
            "from the engineering BOM. Consumables and packaging will be absent."
        )

    unit = Unit(
        serial_number=serial_number,
        part_id=part.id,
        built_to_revision_id=revision.id,
        as_built_baseline_id=await _current_baseline_id(session, part.id),
        status=UnitStatus.IN_PRODUCTION,
        built_at=built_at or datetime.now(timezone.utc),
        plant=plant,
    )
    session.add(unit)
    await session.flush()

    revision_ids = await _revision_ids_by_part_number(session)
    part_ids = await _part_ids_by_number(session)

    recorded = 0
    assigned = 0
    untraced: list[str] = []

    def walk(node, path: tuple[str, ...]) -> None:
        nonlocal recorded, assigned
        here = (*path, node.find_number or node.part_number)
        for child in node.children:
            walk(child, here)
        if not path:
            return  # the root is the unit itself, not a component of it

        lot = lots.get(node.part_number)
        if lot:
            assigned += 1
        elif node.part_class.value not in ("Assembly", "Phantom"):
            untraced.append(node.part_number)

        session.add(
            UnitComponent(
                unit_id=unit.id,
                part_id=part_ids[node.part_number],
                part_revision_id=revision_ids.get((node.part_number, node.revision)),
                quantity=Decimal(str(node.quantity)),
                unit_of_measure=node.unit_of_measure,
                lot_number=lot,
                position=" / ".join(path[1:] + (node.find_number or "",)).strip(" /")
                or None,
                operation_seq=node.operation_seq,
                installed_at=unit.built_at,
            )
        )
        recorded += 1

    walk(bom.tree, ())

    if untraced:
        warnings.append(
            "No lot recorded for: "
            + ", ".join(sorted(set(untraced)))
            + ". Those components cannot be traced backwards from a material "
            "problem."
        )

    audit.record(
        session,
        actor=actor,
        action=AuditAction.CREATE,
        entity_type="Unit",
        entity_id=unit.id,
        after={
            "serial_number": serial_number,
            "part_number": part_number,
            "revision": revision.revision,
            "components": recorded,
            "bom_type": bom_type,
        },
    )
    if commit:
        await session.commit()

    logger.info(
        "Built %s as %s rev %s with %d components from the %s.",
        serial_number,
        part_number,
        revision.revision,
        recorded,
        bom_type,
    )
    return BuildResult(
        serial_number=serial_number,
        part_number=part_number,
        built_to_revision=revision.revision,
        bom_type_used=bom_type,
        components_recorded=recorded,
        lots_assigned=assigned,
        warnings=warnings,
    )


async def _current_baseline_id(session: AsyncSession, part_id):
    return (
        await session.execute(
            select(ConfigurationBaseline.id)
            .where(ConfigurationBaseline.root_part_id == part_id)
            .order_by(ConfigurationBaseline.captured_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _part_ids_by_number(session: AsyncSession) -> dict[str, object]:
    return {
        number: pid
        for pid, number in (
            await session.execute(select(Part.id, Part.part_number))
        ).all()
    }


async def _revision_ids_by_part_number(session: AsyncSession) -> dict[tuple, object]:
    rows = (
        await session.execute(
            select(Part.part_number, PartRevision.revision, PartRevision.id).join(
                PartRevision, PartRevision.part_id == Part.id
            )
        )
    ).all()
    return {(number, revision): rid for number, revision, rid in rows}


# --------------------------------------------------------------------------
# Traceability
# --------------------------------------------------------------------------


async def get_unit_genealogy(
    session: AsyncSession, serial_number: str
) -> UnitGenealogy:
    """What this individual article is actually made of."""
    unit = await _load_unit(session, serial_number)

    rows = (
        await session.execute(
            UNIT_GENEALOGY,
            {
                "serial_number": unit.serial_number,
                "max_depth": MAX_GENEALOGY_DEPTH,
            },
        )
    ).mappings().all()

    part_number = (
        await session.execute(select(Part.part_number).where(Part.id == unit.part_id))
    ).scalar_one()
    revision = None
    if unit.built_to_revision_id is not None:
        revision = (
            await session.execute(
                select(PartRevision.revision).where(
                    PartRevision.id == unit.built_to_revision_id
                )
            )
        ).scalar_one_or_none()
    baseline = None
    if unit.as_built_baseline_id is not None:
        baseline = (
            await session.execute(
                select(ConfigurationBaseline.name).where(
                    ConfigurationBaseline.id == unit.as_built_baseline_id
                )
            )
        ).scalar_one_or_none()

    lines = [
        GenealogyLine(
            part_number=row["part_number"],
            description=row["description"],
            revision=row["revision"],
            quantity=float(row["quantity"]),
            unit_of_measure=row["unit_of_measure"],
            lot_number=row["lot_number"],
            supplier_lot=row["supplier_lot"],
            child_serial_number=row["child_serial_number"],
            position=row["position"],
            operation_seq=row["operation_seq"],
            installed_at=row["installed_at"],
            depth=row["depth"],
            parent_serial=row["parent_serial"],
        )
        for row in rows
    ]

    return UnitGenealogy(
        serial_number=unit.serial_number,
        part_number=part_number,
        built_to_revision=revision,
        status=unit.status,
        built_at=unit.built_at,
        plant=unit.plant,
        customer_ref=unit.customer_ref,
        as_built_baseline=baseline,
        line_count=len(lines),
        lots=sorted({line.lot_number for line in lines if line.lot_number}),
        lines=lines,
    )


async def trace_lot(session: AsyncSession, lot_number: str) -> LotTrace:
    """Every unit containing a given lot of material."""
    lot_number = lot_number.strip()
    if not lot_number:
        raise ToolError("A lot number is required to trace one.")

    rows = (
        await session.execute(
            LOT_TRACE, {"lot_number": lot_number, "max_depth": MAX_GENEALOGY_DEPTH}
        )
    ).mappings().all()

    if not rows:
        known = (
            await session.execute(
                select(UnitComponent.lot_number)
                .where(UnitComponent.lot_number.isnot(None))
                .distinct()
                .order_by(UnitComponent.lot_number)
            )
        ).scalars().all()
        raise ToolError(
            f"No unit contains lot {lot_number!r}. Known lots: {', '.join(known)}"
            if known
            else f"No unit contains lot {lot_number!r}, and no lot numbers have "
            "been recorded against any build."
        )

    units = [
        TracedUnit(
            serial_number=row["serial_number"],
            part_number=row["part_number"],
            status=row["status"],
            built_at=row["built_at"],
            customer_ref=row["customer_ref"],
            depth=row["depth"],
        )
        for row in rows
    ]
    return LotTrace(lot_number=lot_number, unit_count=len(units), units=units)
