"""Per-unit traceability: build records, lot traces, verdicts, NCRs."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal import SYSTEM_PRINCIPAL
from app.domains.ecm.models import EcrStatus
from app.domains.ecm.service import get_change_request
from app.domains.identity.models import Role
from app.domains.pdm.models import PartClass
from app.domains.qms import ncr as ncr_service
from app.domains.qms.models import (
    CapaKind,
    Disposition,
    LabTestRecord,
    NcrSeverity,
    NcrSource,
    NcrStatus,
    TestProtocol,
    TestResult,
    TestSpecLimit,
    Unit,
)
from app.domains.qms.service import (
    build_unit,
    evaluate,
    get_unit_genealogy,
    query_qms_test_metrics,
    trace_lot,
)
from app.tools.registry import ToolError
from tests.conftest import principal_for
from tests.test_pdm_structure import link, make_part

pytestmark = pytest.mark.db

BUILT_AT = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)


@pytest.fixture
async def product(session: AsyncSession):
    """MODULE -> {MATRIX, MAGNET, SEAL}."""
    module, module_rev = await make_part(
        session, "QM-MOD-100", part_class=PartClass.ASSEMBLY
    )
    matrix, _ = await make_part(session, "QM-MAT-200", part_class=PartClass.RAW_MATERIAL)
    magnet, _ = await make_part(session, "QM-MAG-300")
    seal, _ = await make_part(session, "QM-SEA-400")
    await link(session, module_rev, matrix, quantity="8", find_number="110")
    await link(session, module_rev, magnet, quantity="1", find_number="120")
    await link(session, module_rev, seal, quantity="4", find_number="130")
    await session.commit()
    return {"module": module, "matrix": matrix, "magnet": magnet, "seal": seal}


@pytest.fixture
async def protocol(session: AsyncSession, product) -> TestProtocol:
    proto = TestProtocol(
        code="QM-TP-1",
        revision="A",
        name="Acceptance",
        applies_to_part_id=product["module"].id,
    )
    session.add(proto)
    await session.flush()
    session.add_all(
        [
            TestSpecLimit(
                protocol_id=proto.id,
                metric="temperature_span_delta_K",
                lower_limit=15.0,
                upper_limit=18.0,
            ),
            # One-sided on purpose: there is no meaningful floor on pressure
            # drop, and inventing one would fail a genuinely good reading.
            TestSpecLimit(
                protocol_id=proto.id, metric="pressure_drop_mbar", upper_limit=900.0
            ),
        ]
    )
    await session.commit()
    await session.refresh(proto, ["limits"])
    return proto


async def build(session: AsyncSession, serial: str, lots=None, **kwargs):
    return await build_unit(
        session,
        actor=SYSTEM_PRINCIPAL,
        serial_number=serial,
        part_number="QM-MOD-100",
        lots=lots,
        built_at=BUILT_AT,
        **kwargs,
    )


def record(unit_id, span=16.0, pressure=850.0, hz=2.5, watts=1000.0, **kwargs):
    return LabTestRecord(
        unit_id=unit_id,
        recorded_at=BUILT_AT,
        temperature_span_delta_K=span,
        pressure_drop_mbar=pressure,
        magnetization_cycles_hz=hz,
        cooling_capacity_W=watts,
        **kwargs,
    )


# --------------------------------------------------------------------------
# Build records
# --------------------------------------------------------------------------


async def test_building_a_unit_snapshots_the_structure(
    session: AsyncSession, product
) -> None:
    result = await build(session, "QM-U-001", lots={"QM-MAT-200": "MAT-L-01"})
    assert result.components_recorded == 3
    assert result.lots_assigned == 1

    genealogy = await get_unit_genealogy(session, "QM-U-001")
    assert {line.part_number for line in genealogy.lines} == {
        "QM-MAT-200",
        "QM-MAG-300",
        "QM-SEA-400",
    }
    matrix = next(l for l in genealogy.lines if l.part_number == "QM-MAT-200")
    assert matrix.quantity == 8
    assert matrix.lot_number == "MAT-L-01"


async def test_components_without_a_lot_are_reported_not_hidden(
    session: AsyncSession, product
) -> None:
    result = await build(session, "QM-U-002", lots={"QM-MAT-200": "MAT-L-01"})
    # The two components with no lot are exactly the ones a recall could not
    # trace, so the build result has to name them.
    assert any("QM-MAG-300" in warning for warning in result.warnings)
    assert any("QM-SEA-400" in warning for warning in result.warnings)


async def test_a_serial_is_built_once(session: AsyncSession, product) -> None:
    await build(session, "QM-U-003")
    with pytest.raises(ToolError, match="already been built"):
        await build(session, "QM-U-003")


async def test_the_build_record_does_not_move_when_the_bom_does(
    session: AsyncSession, product
) -> None:
    """The whole point of a snapshot rather than a view over today's BOM."""
    await build(session, "QM-U-004", lots={"QM-MAT-200": "MAT-L-01"})

    # Engineering changes the design afterwards.
    extra, _ = await make_part(session, "QM-NEW-500")
    module_rev = (
        await session.execute(
            select(Unit.built_to_revision_id).where(Unit.serial_number == "QM-U-004")
        )
    ).scalar_one()
    from app.domains.pdm.models import PartRevision

    revision = await session.get(PartRevision, module_rev)
    await link(session, revision, extra, quantity="2", find_number="140")
    await session.commit()

    genealogy = await get_unit_genealogy(session, "QM-U-004")
    assert "QM-NEW-500" not in {line.part_number for line in genealogy.lines}


async def test_building_an_unknown_part_is_refused(
    session: AsyncSession, product
) -> None:
    with pytest.raises(ToolError, match="No part named"):
        await build_unit(
            session,
            actor=SYSTEM_PRINCIPAL,
            serial_number="QM-U-005",
            part_number="NOPE-000",
        )


# --------------------------------------------------------------------------
# Traceability
# --------------------------------------------------------------------------


async def test_a_lot_traces_to_every_unit_containing_it(
    session: AsyncSession, product
) -> None:
    await build(session, "QM-U-010", lots={"QM-MAG-300": "MAG-L-BAD"})
    await build(session, "QM-U-011", lots={"QM-MAG-300": "MAG-L-BAD"})
    await build(session, "QM-U-012", lots={"QM-MAG-300": "MAG-L-GOOD"})

    trace = await trace_lot(session, "MAG-L-BAD")
    assert {unit.serial_number for unit in trace.units} == {"QM-U-010", "QM-U-011"}
    assert trace.unit_count == 2


async def test_an_unknown_lot_lists_the_known_ones(
    session: AsyncSession, product
) -> None:
    await build(session, "QM-U-013", lots={"QM-MAG-300": "MAG-L-GOOD"})
    with pytest.raises(ToolError, match="MAG-L-GOOD"):
        await trace_lot(session, "NOT-A-LOT")


async def test_genealogy_reaches_through_a_serialised_subassembly(
    session: AsyncSession, product
) -> None:
    """A product built from serialised modules reads as one tree."""
    system, system_rev = await make_part(
        session, "QM-SYS-900", part_class=PartClass.ASSEMBLY
    )
    await link(session, system_rev, product["module"], quantity="1", find_number="100")
    await session.commit()

    await build(session, "QM-U-020", lots={"QM-MAT-200": "MAT-L-77"})

    await build_unit(
        session,
        actor=SYSTEM_PRINCIPAL,
        serial_number="QM-S-001",
        part_number="QM-SYS-900",
        built_at=BUILT_AT,
    )
    # Link the built module into the system's record.
    from app.domains.qms.models import UnitComponent

    line = (
        await session.execute(
            select(UnitComponent)
            .join(Unit, Unit.id == UnitComponent.unit_id)
            .where(Unit.serial_number == "QM-S-001")
        )
    ).scalars().first()
    line.child_serial_number = "QM-U-020"
    await session.commit()

    genealogy = await get_unit_genealogy(session, "QM-S-001")
    depths = {line.part_number: line.depth for line in genealogy.lines}
    assert depths["QM-MOD-100"] == 0
    # Reached through the serialised module, not listed directly on the system.
    assert depths["QM-MAT-200"] == 1
    assert "MAT-L-77" in genealogy.lots


async def test_a_lot_inside_a_serialised_subassembly_traces_to_the_parent(
    session: AsyncSession, product
) -> None:
    system, system_rev = await make_part(
        session, "QM-SYS-901", part_class=PartClass.ASSEMBLY
    )
    await link(session, system_rev, product["module"], quantity="1", find_number="100")
    await session.commit()

    await build(session, "QM-U-030", lots={"QM-MAT-200": "MAT-L-88"})
    await build_unit(
        session,
        actor=SYSTEM_PRINCIPAL,
        serial_number="QM-S-002",
        part_number="QM-SYS-901",
        built_at=BUILT_AT,
    )
    from app.domains.qms.models import UnitComponent

    line = (
        await session.execute(
            select(UnitComponent)
            .join(Unit, Unit.id == UnitComponent.unit_id)
            .where(Unit.serial_number == "QM-S-002")
        )
    ).scalars().first()
    line.child_serial_number = "QM-U-030"
    await session.commit()

    trace = await trace_lot(session, "MAT-L-88")
    # Both the module that contains the material and the system that contains
    # the module. Stopping at the module would understate the recall.
    assert {unit.serial_number for unit in trace.units} == {"QM-U-030", "QM-S-002"}


# --------------------------------------------------------------------------
# Acceptance limits
# --------------------------------------------------------------------------


def test_a_reading_inside_every_band_passes(protocol) -> None:
    result, breaches = evaluate(record(None, span=16.0, pressure=850.0), protocol)
    assert result is TestResult.PASS
    assert breaches == []


def test_a_reading_below_a_floor_fails_and_names_the_metric(protocol) -> None:
    result, breaches = evaluate(record(None, span=14.9), protocol)
    assert result is TestResult.FAIL
    assert [b["metric"] for b in breaches] == ["temperature_span_delta_K"]
    assert breaches[0]["value"] == 14.9
    assert breaches[0]["lower_limit"] == 15.0


def test_a_one_sided_limit_does_not_fail_a_low_reading(protocol) -> None:
    # Pressure drop has a ceiling and no floor. A very low value is unusual but
    # not out of specification, and reporting it as a failure would be wrong.
    result, _ = evaluate(record(None, pressure=1.0), protocol)
    assert result is TestResult.PASS

    result, breaches = evaluate(record(None, pressure=950.0), protocol)
    assert result is TestResult.FAIL
    assert breaches[0]["upper_limit"] == 900.0


def test_a_reading_with_no_protocol_is_data_but_not_a_verdict() -> None:
    result, breaches = evaluate(record(None, span=1.0), None)
    assert result is TestResult.NOT_EVALUATED
    assert breaches == []


async def test_stored_verdicts_survive_a_later_change_to_the_limits(
    session: AsyncSession, product, protocol
) -> None:
    """Tightening a specification must not retroactively fail a passed unit."""
    await build(session, "QM-U-040")
    unit = (
        await session.execute(select(Unit).where(Unit.serial_number == "QM-U-040"))
    ).scalar_one()

    reading = record(unit.id, span=15.5, protocol_id=protocol.id)
    reading.result, reading.breaches = evaluate(reading, protocol)
    session.add(reading)
    await session.commit()
    assert reading.result is TestResult.PASS

    # Quality raises the floor above the reading that already passed.
    span_limit = next(
        l for l in protocol.limits if l.metric == "temperature_span_delta_K"
    )
    span_limit.lower_limit = 16.0
    await session.commit()

    metrics = await query_qms_test_metrics(session, "QM-U-040")
    assert metrics.records[0].result is TestResult.PASS
    assert metrics.pass_count == 1


async def test_metrics_report_the_limits_alongside_the_readings(
    session: AsyncSession, product, protocol
) -> None:
    await build(session, "QM-U-041")
    unit = (
        await session.execute(select(Unit).where(Unit.serial_number == "QM-U-041"))
    ).scalar_one()
    reading = record(unit.id, protocol_id=protocol.id)
    reading.result, reading.breaches = evaluate(reading, protocol)
    session.add(reading)
    await session.commit()

    metrics = await query_qms_test_metrics(session, "QM-U-041")
    span = next(s for s in metrics.summaries if s.metric == "temperature_span_delta_K")
    assert (span.lower_limit, span.upper_limit) == (15.0, 18.0)
    assert metrics.protocol == "QM-TP-1 rev A"


async def test_a_unit_with_no_readings_says_so(
    session: AsyncSession, product
) -> None:
    await build(session, "QM-U-042")
    with pytest.raises(ToolError, match="no lab test records"):
        await query_qms_test_metrics(session, "QM-U-042")


# --------------------------------------------------------------------------
# Non-conformance
# --------------------------------------------------------------------------


async def raise_ncr(session, actor, **kwargs):
    defaults = dict(
        title="Partial demagnetisation at the array edge",
        description="Span collapsed by 0.9 K after roughly 400 hours in service.",
        source=NcrSource.FIELD,
        severity=NcrSeverity.MAJOR,
    )
    return await ncr_service.raise_non_conformance(
        session, actor=actor, **{**defaults, **kwargs}
    )


async def test_a_non_conformance_needs_something_to_be_against(
    session: AsyncSession, product, user_factory
) -> None:
    quality = principal_for(await user_factory(Role.QUALITY))
    with pytest.raises(ToolError, match="has to be against something"):
        await raise_ncr(session, quality)


async def test_a_lot_scoped_ncr_resolves_its_affected_units(
    session: AsyncSession, product, user_factory
) -> None:
    """Raised against a batch; the units come from the build records."""
    quality = principal_for(await user_factory(Role.QUALITY))
    await build(session, "QM-U-050", lots={"QM-MAG-300": "MAG-L-BAD"})
    await build(session, "QM-U-051", lots={"QM-MAG-300": "MAG-L-BAD"})
    await build(session, "QM-U-052", lots={"QM-MAG-300": "MAG-L-GOOD"})

    report = await raise_ncr(session, quality, lot_number="MAG-L-BAD")
    assert set(report.affected_units) == {"QM-U-050", "QM-U-051"}
    assert report.status is NcrStatus.OPEN
    assert report.disposition is Disposition.PENDING


async def test_use_as_is_and_scrap_require_a_written_justification(
    session: AsyncSession, product, user_factory
) -> None:
    quality = principal_for(await user_factory(Role.QUALITY))
    report = await raise_ncr(session, quality, part_number="QM-MAG-300")

    with pytest.raises(ToolError, match="written justification"):
        await ncr_service.set_disposition(
            session,
            actor=quality,
            number=report.number,
            disposition=Disposition.USE_AS_IS,
        )
    # Rework needs no essay; the decision speaks for itself.
    updated = await ncr_service.set_disposition(
        session, actor=quality, number=report.number, disposition=Disposition.REWORK
    )
    assert updated.status is NcrStatus.DISPOSITIONED


async def test_closing_needs_a_disposition_and_finished_actions(
    session: AsyncSession, product, user_factory
) -> None:
    quality = principal_for(await user_factory(Role.QUALITY))
    report = await raise_ncr(session, quality, part_number="QM-MAG-300")

    with pytest.raises(ToolError, match="no disposition"):
        await ncr_service.close_non_conformance(
            session, actor=quality, number=report.number
        )

    await ncr_service.set_disposition(
        session, actor=quality, number=report.number, disposition=Disposition.REWORK
    )
    await ncr_service.add_action(
        session,
        actor=quality,
        number=report.number,
        kind=CapaKind.CORRECTIVE,
        description="Replace the array on the affected units.",
        due_date=date(2026, 12, 1),
    )
    with pytest.raises(ToolError, match="outstanding action"):
        await ncr_service.close_non_conformance(
            session, actor=quality, number=report.number
        )


async def test_escalation_opens_a_change_request_carrying_the_evidence(
    session: AsyncSession, product, user_factory
) -> None:
    """The join between finding a problem and fixing it properly."""
    quality = principal_for(await user_factory(Role.QUALITY))
    await build(session, "QM-U-060", lots={"QM-MAG-300": "MAG-L-BAD"})
    report = await raise_ncr(session, quality, lot_number="MAG-L-BAD")

    escalated = await ncr_service.escalate_to_change_request(
        session,
        actor=quality,
        number=report.number,
        proposed_solution="Move to a higher intrinsic coercivity magnet grade.",
    )
    assert escalated.escalated_ecr_number is not None

    ecr = await get_change_request(session, escalated.escalated_ecr_number)
    assert ecr.status is EcrStatus.DRAFT
    # The part carrying the bad lot, derived from the build records.
    assert ecr.affected_part_numbers == ["QM-MAG-300"]
    assert report.number in ecr.problem_statement
    assert "QM-U-060" in ecr.problem_statement
    # A field finding raises a field-origin change, at high priority.
    assert ecr.origin.value == "Field"
    assert ecr.priority.value == "High"


async def test_a_critical_finding_escalates_as_urgent(
    session: AsyncSession, product, user_factory
) -> None:
    quality = principal_for(await user_factory(Role.QUALITY))
    report = await raise_ncr(
        session,
        quality,
        part_number="QM-MAG-300",
        severity=NcrSeverity.CRITICAL,
        source=NcrSource.FINAL_TEST,
    )
    escalated = await ncr_service.escalate_to_change_request(
        session,
        actor=quality,
        number=report.number,
        proposed_solution="Requalify the magnet supplier.",
    )
    ecr = await get_change_request(session, escalated.escalated_ecr_number)
    assert ecr.priority.value == "Urgent"
    assert ecr.origin.value == "Quality"


async def test_a_non_conformance_escalates_once(
    session: AsyncSession, product, user_factory
) -> None:
    quality = principal_for(await user_factory(Role.QUALITY))
    report = await raise_ncr(session, quality, part_number="QM-MAG-300")
    await ncr_service.escalate_to_change_request(
        session, actor=quality, number=report.number, proposed_solution="Change grade."
    )
    with pytest.raises(ToolError, match="already been escalated"):
        await ncr_service.escalate_to_change_request(
            session,
            actor=quality,
            number=report.number,
            proposed_solution="Change grade again.",
        )


# --------------------------------------------------------------------------
# Impact analysis now runs on real build records
# --------------------------------------------------------------------------


async def test_change_impact_finds_evidence_through_the_as_built_record(
    session: AsyncSession, product, protocol, user_factory
) -> None:
    """A change to a component reaches the units that actually contain it.

    Not the units the *current* BOM says would contain it — the ones whose
    build record does.
    """
    from app.domains.ecm.impact import assess

    await build(session, "QM-U-070", lots={"QM-MAG-300": "MAG-L-01"})
    unit = (
        await session.execute(select(Unit).where(Unit.serial_number == "QM-U-070"))
    ).scalar_one()
    reading = record(unit.id, protocol_id=protocol.id)
    reading.result, reading.breaches = evaluate(reading, protocol)
    session.add(reading)
    await session.commit()

    findings, summary = await assess(session, ["QM-MAG-300"])
    assert [e.serial_number for e in findings.revalidation_required] == ["QM-U-070"]
    assert "re-validating" in summary


async def test_a_component_no_unit_was_built_with_flags_no_evidence(
    session: AsyncSession, product
) -> None:
    from app.domains.ecm.impact import assess

    findings, _ = await assess(session, ["QM-MAG-300"])
    assert findings.revalidation_required == []
