"""Deriving the manufacturing view from the engineering view.

The EBOM says what the product *is*. The MBOM says how it gets built: with the
water/alcohol charge that no drawing shows, the packaging it ships in, the
kitting groups the line finds convenient, and every line assigned to the routing
step that consumes it.

The transition between them is the most consequential handoff in hardware
manufacturing, and the usual way of doing it — copy the EBOM once, then edit the
copy by hand forever — loses the reason for every difference the moment the
person who made it moves on. Here the differences are stored as `MbomDelta`
rows and replayed:

    MBOM = copy(released EBOM) then apply(deltas in sequence)

so the gap between the two views is a queryable list with a rationale against
each entry, and the MBOM can be rebuilt after an engineering change instead of
being reconciled by hand.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.audit import AuditAction
from app.core.principal import Principal
from app.domains.pdm.models import (
    BomEdge,
    BomType,
    MbomDelta,
    MbomDeltaType,
    Operation,
    Part,
    PartRevision,
)
from app.domains.pdm.schemas import (
    MbomDeltaOut,
    MbomDerivationResult,
    OperationOut,
)
from app.tools.registry import ToolError

logger = logging.getLogger(__name__)


async def _root_revision(session: AsyncSession, part_number: str) -> tuple[Part, PartRevision]:
    part = (
        await session.execute(select(Part).where(Part.part_number == part_number))
    ).scalar_one_or_none()
    if part is None:
        raise ToolError(f"No part named {part_number!r}.")

    revisions = (
        await session.execute(
            select(PartRevision).where(PartRevision.part_id == part.id)
        )
    ).scalars().all()
    if not revisions:
        raise ToolError(f"{part_number} has no revisions to derive an MBOM from.")

    released = [rev for rev in revisions if rev.is_released]
    if released:
        chosen = max(released, key=lambda rev: (rev.released_at or rev.created_at))
    else:
        # Deriving from an unreleased design is legitimate during pilot builds,
        # but the planner should know the ground can still move.
        chosen = max(revisions, key=lambda rev: rev.created_at)
    return part, chosen


async def _subtree_revision_ids(
    session: AsyncSession, root: PartRevision, bom_type: BomType
) -> set[uuid.UUID]:
    """Every parent revision reachable from `root` through edges of one type.

    Needed because regenerating an MBOM must clear the previous one, and the
    previous one is spread across every assembly in the tree, not just the top.
    """
    seen: set[uuid.UUID] = {root.id}
    frontier = [root.id]

    while frontier:
        edges = (
            await session.execute(
                select(BomEdge.child_part_id, BomEdge.child_revision_id).where(
                    BomEdge.parent_revision_id.in_(frontier),
                    BomEdge.bom_type == bom_type,
                )
            )
        ).all()
        if not edges:
            break

        child_part_ids = [row[0] for row in edges]
        pinned = {row[1] for row in edges if row[1] is not None}

        # Unpinned children resolve to their own revisions; take all of them
        # rather than re-implementing the "latest released" rule here, because
        # clearing one revision too many is harmless and missing one leaves
        # orphaned MBOM lines behind.
        child_revisions = (
            await session.execute(
                select(PartRevision.id).where(PartRevision.part_id.in_(child_part_ids))
            )
        ).scalars().all()

        frontier = [rid for rid in {*pinned, *child_revisions} if rid not in seen]
        seen.update(frontier)

    return seen


async def derive_mbom(
    session: AsyncSession,
    *,
    actor: Principal,
    part_number: str,
    commit: bool = True,
) -> MbomDerivationResult:
    """Rebuild the MBOM for a product from its EBOM plus the stored deltas.

    Idempotent: running it twice produces the same MBOM, because it clears the
    previous derivation first rather than layering on top of it.
    """
    part_number = part_number.strip().upper()
    part, root = await _root_revision(session, part_number)
    warnings: list[str] = []
    if not root.is_released:
        warnings.append(
            f"Derived from revision {root.revision}, which is "
            f"{root.lifecycle_state.value.lower()} rather than released. The "
            "MBOM will change if the design does."
        )

    # --- Clear the previous derivation ------------------------------------
    stale_scope = await _subtree_revision_ids(session, root, BomType.MBOM)
    await session.execute(
        delete(BomEdge).where(
            BomEdge.parent_revision_id.in_(stale_scope),
            BomEdge.bom_type == BomType.MBOM,
        )
    )

    # --- Copy the engineering structure -----------------------------------
    ebom_scope = await _subtree_revision_ids(session, root, BomType.EBOM)
    ebom_edges = (
        await session.execute(
            select(BomEdge).where(
                BomEdge.parent_revision_id.in_(ebom_scope),
                BomEdge.bom_type == BomType.EBOM,
            )
        )
    ).scalars().all()

    copied = 0
    for edge in ebom_edges:
        session.add(
            BomEdge(
                parent_revision_id=edge.parent_revision_id,
                child_part_id=edge.child_part_id,
                child_revision_id=edge.child_revision_id,
                bom_type=BomType.MBOM,
                quantity=edge.quantity,
                unit_of_measure=edge.unit_of_measure,
                find_number=edge.find_number,
                reference_designator=edge.reference_designator,
                effective_from=edge.effective_from,
                effective_to=edge.effective_to,
                effective_from_serial=edge.effective_from_serial,
                eco_in_id=edge.eco_in_id,
                eco_out_id=edge.eco_out_id,
                notes=edge.notes,
            )
        )
        copied += 1
    await session.flush()

    if copied == 0:
        warnings.append(
            f"{part_number} has no EBOM lines, so the MBOM contains only what "
            "the deltas add."
        )

    # --- Replay the deltas -------------------------------------------------
    deltas = (
        await session.execute(
            select(MbomDelta)
            .where(MbomDelta.root_revision_id == root.id)
            .order_by(MbomDelta.sequence)
        )
    ).scalars().all()

    applied = 0
    for delta in deltas:
        outcome = await _apply_delta(session, root=root, delta=delta)
        if outcome is not None:
            warnings.append(outcome)
            continue
        applied += 1
    await session.flush()

    remaining_scope = await _subtree_revision_ids(session, root, BomType.MBOM)
    edges_after = (
        await session.execute(
            select(BomEdge).where(
                BomEdge.parent_revision_id.in_(remaining_scope),
                BomEdge.bom_type == BomType.MBOM,
            )
        )
    ).scalars().all()

    operations = (
        await session.execute(
            select(Operation)
            .where(Operation.root_revision_id == root.id)
            .order_by(Operation.op_seq)
        )
    ).scalars().all()

    result = MbomDerivationResult(
        root_part_number=part.part_number,
        root_revision=root.revision,
        edges_copied_from_ebom=copied,
        deltas_applied=applied,
        edges_after=len(edges_after),
        deltas=[await _delta_out(session, delta) for delta in deltas],
        operations=[
            OperationOut(
                op_seq=op.op_seq,
                work_center=op.work_center,
                description=op.description,
                setup_minutes=float(op.setup_minutes),
                run_minutes=float(op.run_minutes),
            )
            for op in operations
        ],
        warnings=warnings,
    )

    if commit:
        audit.record(
            session,
            actor=actor,
            action=AuditAction.UPDATE,
            entity_type="MBOM",
            entity_id=f"{part.part_number}@{root.revision}",
            after={
                "edges_copied_from_ebom": copied,
                "deltas_applied": applied,
                "edges_after": len(edges_after),
            },
            reason="MBOM re-derived from the EBOM and stored deltas.",
        )
        await session.commit()

    logger.info(
        "Derived MBOM for %s rev %s: %d copied, %d deltas, %d lines.",
        part.part_number,
        root.revision,
        copied,
        applied,
        len(edges_after),
    )
    return result


async def _apply_delta(
    session: AsyncSession, *, root: PartRevision, delta: MbomDelta
) -> str | None:
    """Apply one delta. Returns a warning string if it could not be applied.

    A delta that no longer matches anything is reported rather than raised: the
    EBOM has moved on and the planner needs to know which instruction is now
    stale, not to have the whole rebuild fail.
    """
    parent_revision_id = root.id
    if delta.parent_part_id is not None:
        parent_revision = (
            await session.execute(
                select(PartRevision)
                .where(PartRevision.part_id == delta.parent_part_id)
                .order_by(PartRevision.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if parent_revision is None:
            return f"Delta {delta.sequence}: target assembly has no revision; skipped."
        parent_revision_id = parent_revision.id

    if delta.delta_type is MbomDeltaType.ADD:
        if delta.child_part_id is None:
            return f"Delta {delta.sequence}: ADD with no component; skipped."
        session.add(
            BomEdge(
                parent_revision_id=parent_revision_id,
                child_part_id=delta.child_part_id,
                bom_type=BomType.MBOM,
                quantity=delta.quantity if delta.quantity is not None else Decimal(1),
                unit_of_measure=delta.unit_of_measure or "ea",
                operation_seq=delta.operation_seq,
                is_phantom=bool(delta.is_phantom),
                scrap_factor=delta.scrap_factor or Decimal(0),
                notes=delta.rationale,
            )
        )
        return None

    edge = (
        await session.execute(
            select(BomEdge).where(
                BomEdge.parent_revision_id == parent_revision_id,
                BomEdge.child_part_id == delta.child_part_id,
                BomEdge.bom_type == BomType.MBOM,
            )
        )
    ).scalars().first()

    if edge is None:
        return (
            f"Delta {delta.sequence} ({delta.delta_type.value}): no matching MBOM "
            "line — the EBOM may have changed since the delta was written."
        )

    if delta.delta_type is MbomDeltaType.REMOVE:
        await session.delete(edge)
    elif delta.delta_type is MbomDeltaType.REQUANTIFY:
        if delta.quantity is None:
            return f"Delta {delta.sequence}: REQUANTIFY with no quantity; skipped."
        edge.quantity = delta.quantity
        if delta.unit_of_measure:
            edge.unit_of_measure = delta.unit_of_measure
        if delta.scrap_factor is not None:
            edge.scrap_factor = delta.scrap_factor
    elif delta.delta_type is MbomDeltaType.PHANTOM:
        edge.is_phantom = True if delta.is_phantom is None else delta.is_phantom
    elif delta.delta_type is MbomDeltaType.ROUTE:
        edge.operation_seq = delta.operation_seq

    edge.notes = delta.rationale
    return None


async def _delta_out(session: AsyncSession, delta: MbomDelta) -> MbomDeltaOut:
    async def number_for(part_id: uuid.UUID | None) -> str | None:
        if part_id is None:
            return None
        return (
            await session.execute(select(Part.part_number).where(Part.id == part_id))
        ).scalar_one_or_none()

    return MbomDeltaOut(
        id=delta.id,
        sequence=delta.sequence,
        delta_type=delta.delta_type,
        parent_part_number=await number_for(delta.parent_part_id),
        child_part_number=await number_for(delta.child_part_id),
        quantity=float(delta.quantity) if delta.quantity is not None else None,
        unit_of_measure=delta.unit_of_measure,
        operation_seq=delta.operation_seq,
        is_phantom=delta.is_phantom,
        scrap_factor=(
            float(delta.scrap_factor) if delta.scrap_factor is not None else None
        ),
        rationale=delta.rationale,
    )
