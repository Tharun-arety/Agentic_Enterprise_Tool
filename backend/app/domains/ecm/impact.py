"""Impact assessment: what a proposed change would actually reach.

The value of a change process is not the speed at which it approves things. It
is whether the board can see, before it votes, everything the change touches.
This module answers that from the data rather than from someone's recollection:

*   which assemblies contain the affected parts, at any depth, and which
    finished products sit above them;
*   which drawings and work instructions are attached to them and will need
    reissuing;
*   which recorded test evidence was taken against a configuration the change
    would alter, and therefore stops being valid;
*   which captured baselines contain the affected parts;
*   what the standard cost does.

Anything it cannot determine is returned in `gaps` rather than omitted. An
assessment that silently leaves out the part it could not price reads exactly
like one where the price did not change.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ecm.schemas import (
    AffectedAssembly,
    AffectedDocument,
    AffectedProduct,
    AffectedTestEvidence,
    CostImpact,
    ImpactFindings,
)
from app.domains.controlling.models import CostRollupSnapshot
from app.domains.pdm.models import (
    ConfigurationBaseline,
    Document,
    Part,
)
from app.domains.pdm.service import get_where_used
from app.domains.qms.models import LabTestRecord, Unit
from app.domains.qms.queries import MAX_GENEALOGY_DEPTH, UNITS_CONTAINING_PART

logger = logging.getLogger(__name__)


async def assess(
    session: AsyncSession, part_numbers: list[str], as_of: date | None = None
) -> tuple[ImpactFindings, str]:
    """Return the findings and a one-paragraph summary."""
    effective = as_of or datetime.now(timezone.utc).date()
    findings = ImpactFindings(affected_items=sorted(set(part_numbers)))

    assemblies: dict[str, AffectedAssembly] = {}
    products: dict[str, AffectedProduct] = {}
    # Every part whose configuration the change reaches: the affected items
    # themselves plus everything containing them. Test evidence and documents
    # are gathered against this whole set, because a measurement taken on the
    # parent assembly is invalidated by a change to the child.
    reached: set[str] = set(findings.affected_items)

    for part_number in findings.affected_items:
        part = (
            await session.execute(
                select(Part).where(Part.part_number == part_number)
            )
        ).scalar_one_or_none()
        if part is None:
            findings.gaps.append(f"{part_number} is not in the part master.")
            continue
        if part.is_configuration_item:
            findings.configuration_items.append(part_number)

        used = await get_where_used(session, part_number, as_of=effective)
        for row in used.rows:
            reached.add(row.part_number)
            existing = assemblies.get(row.part_number)
            if existing is None or row.depth < existing.depth:
                assemblies[row.part_number] = AffectedAssembly(
                    part_number=row.part_number,
                    revision=row.revision,
                    depth=row.depth,
                    quantity=row.quantity,
                )
            if row.is_top_level:
                product = products.setdefault(
                    row.part_number,
                    AffectedProduct(
                        part_number=row.part_number,
                        description=row.description,
                        revision=row.revision,
                    ),
                )
                if row.via_part_number not in product.reached_via:
                    product.reached_via.append(row.via_part_number)

        if not used.rows:
            findings.gaps.append(
                f"{part_number} is not used in any assembly, so nothing above it "
                "is affected. Check that is expected before releasing."
            )

    findings.affected_assemblies = sorted(
        assemblies.values(), key=lambda row: (row.depth, row.part_number)
    )
    findings.affected_products = sorted(
        products.values(), key=lambda row: row.part_number
    )

    findings.affected_documents = await _documents_for(session, reached)
    findings.revalidation_required = await _test_evidence_for(session, reached)
    findings.affected_baselines = await _baselines_for(session, reached)
    findings.cost_impact = await _cost_positions(
        session,
        findings.affected_items,
        [product.part_number for product in findings.affected_products],
    )

    return findings, _summarise(findings)


async def _documents_for(
    session: AsyncSession, part_numbers: set[str]
) -> list[AffectedDocument]:
    if not part_numbers:
        return []
    rows = (
        await session.execute(
            select(Document)
            .join(Part, Part.id == Document.related_part_id)
            .where(Part.part_number.in_(part_numbers))
            .order_by(Document.document_number)
        )
    ).scalars().all()

    out: list[AffectedDocument] = []
    for document in rows:
        await session.refresh(document, ["revisions"])
        out.append(
            AffectedDocument(
                document_number=document.document_number,
                title=document.title,
                kind=document.kind.value,
                latest_revision=(
                    document.revisions[-1].revision if document.revisions else None
                ),
            )
        )
    return out


async def _test_evidence_for(
    session: AsyncSession, part_numbers: set[str]
) -> list[AffectedTestEvidence]:
    """Recorded measurements taken against a configuration this would alter.

    Resolved from the **as-built records**, not from the current BOM. A unit
    tested last year contains what it contained when it was built, and that is
    what decides whether its measurements survive the change. Asking today's
    structure would both miss units whose component has since been designed out
    and wrongly implicate units built before it was designed in.
    """
    if not part_numbers:
        return []

    affected = (
        await session.execute(
            UNITS_CONTAINING_PART,
            {"part_numbers": sorted(part_numbers), "max_depth": MAX_GENEALOGY_DEPTH},
        )
    ).mappings().all()
    if not affected:
        return []

    serials = {row["serial_number"] for row in affected}
    rows = (
        await session.execute(
            select(
                Unit.serial_number,
                Part.part_number,
                func.count(LabTestRecord.id),
                func.max(LabTestRecord.recorded_at),
            )
            .join(LabTestRecord, LabTestRecord.unit_id == Unit.id)
            .join(Part, Part.id == Unit.part_id)
            .where(Unit.serial_number.in_(serials))
            .group_by(Unit.serial_number, Part.part_number)
            .order_by(Unit.serial_number)
        )
    ).all()

    return [
        AffectedTestEvidence(
            serial_number=serial,
            part_number=part_number,
            sample_count=count,
            latest_recorded_at=latest,
        )
        for serial, part_number, count, latest in rows
    ]


async def _baselines_for(session: AsyncSession, part_numbers: set[str]) -> list[str]:
    baselines = (
        await session.execute(
            select(ConfigurationBaseline).order_by(ConfigurationBaseline.captured_at)
        )
    ).scalars().all()
    return [
        baseline.name
        for baseline in baselines
        if any(
            line.get("part_number") in part_numbers
            for line in (baseline.snapshot or [])
        )
    ]


async def _cost_positions(
    session: AsyncSession,
    part_numbers: list[str],
    product_numbers: list[str],
) -> list[CostImpact]:
    """Baseline-to-baseline rollup delta, or an explicit partial cost position."""
    out: list[CostImpact] = []
    # Rollup snapshots belong to the affected top-level products rather than
    # each leaf named on an ECR. Surface those product deltas first.
    for product_number in product_numbers:
        product = (
            await session.execute(
                select(Part).where(Part.part_number == product_number)
            )
        ).scalar_one_or_none()
        if product is None:
            continue
        snapshots = list(
            (
                await session.execute(
                    select(CostRollupSnapshot, ConfigurationBaseline.name)
                    .join(
                        ConfigurationBaseline,
                        ConfigurationBaseline.id == CostRollupSnapshot.baseline_id,
                    )
                    .where(CostRollupSnapshot.part_id == product.id)
                    .order_by(CostRollupSnapshot.captured_at.desc())
                    .limit(2)
                )
            ).all()
        )
        if len(snapshots) == 2:
            after_snapshot, after_name = snapshots[0]
            before_snapshot, before_name = snapshots[1]
            before = float(before_snapshot.total_cost)
            after = float(after_snapshot.total_cost)
            out.append(
                CostImpact(
                    part_number=product_number,
                    baseline_from=before_name,
                    baseline_to=after_name,
                    before=before,
                    after=after,
                    delta=after - before,
                    note=f"Immutable rollup delta: {before_name} -> {after_name} (EUR).",
                )
            )

    for part_number in part_numbers:
        part = (
            await session.execute(
                select(Part).where(Part.part_number == part_number)
            )
        ).scalar_one_or_none()
        if part is None:
            continue
        out.append(
            CostImpact(
                part_number=part_number,
                before=float(part.standard_cost) if part.standard_cost is not None else None,
                after=None,
                delta=None,
                note=(
                    "No standard cost on record."
                    if part.standard_cost is None
                    else "Current standard cost; capture two baseline rollups for an ECO delta."
                ),
            )
        )
    return out


def _summarise(findings: ImpactFindings) -> str:
    parts = ", ".join(findings.affected_items) or "nothing"
    pieces = [f"Affects {parts}."]

    if findings.affected_products:
        names = ", ".join(product.part_number for product in findings.affected_products)
        pieces.append(f"Reaches {len(findings.affected_products)} product(s): {names}.")
    else:
        pieces.append("Reaches no finished product.")

    if findings.affected_assemblies:
        pieces.append(f"{len(findings.affected_assemblies)} assembly/assemblies above it.")
    if findings.configuration_items:
        pieces.append(
            f"{len(findings.configuration_items)} tracked configuration item(s) involved."
        )
    if findings.revalidation_required:
        serials = ", ".join(
            evidence.serial_number for evidence in findings.revalidation_required
        )
        pieces.append(
            f"Test evidence on {serials} was recorded against the current "
            "configuration and needs re-validating."
        )
    if findings.affected_documents:
        docs = ", ".join(doc.document_number for doc in findings.affected_documents)
        pieces.append(f"Documents to reissue: {docs}.")
    if findings.affected_baselines:
        pieces.append(f"{len(findings.affected_baselines)} captured baseline(s) contain it.")
    if findings.gaps:
        pieces.append(f"{len(findings.gaps)} item(s) could not be assessed.")

    return " ".join(pieces)
