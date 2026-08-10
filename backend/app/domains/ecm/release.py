"""Releasing a change order: the moment the configuration actually moves.

One transaction, because a half-released change is the worst state this system
can be in — new revisions with no notice, or a notice for structure that never
changed. Everything below either happens together or not at all:

1.  Every assembly the order touches gets a **new revision**, and its previous
    revision is marked superseded.
2.  The previous revision's lines are **copied forward**, then the order's line
    items are applied to the copy. The old revision keeps its own lines
    untouched, which is what lets a unit built last year still resolve to what
    it actually contains.
3.  A **baseline** is captured for each finished product above the change.
4.  A **change notice** is issued to the affected internal roles and external
    partners.
5.  The order's text is **indexed into the knowledge corpus**, so the reason
    for the change is retrievable by the same search that answers "why is this
    built this way?" — the corpus populates itself from the transactional
    record instead of being a hand-maintained fixture.

Note what step 1 does *not* do: it does not touch the assemblies above the ones
being changed. Their lines point at the child *part* and resolve to its latest
released revision at query time, so they pick up the new revision on their own.
That is the whole reason edges bind a parent revision to a child part rather
than to a child revision.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.audit import AuditAction
from app.core.embeddings import get_embedding_provider
from app.core.principal import Principal
from app.domains.controlling.service import capture_snapshot
from app.domains.ecm.models import (
    ChangeAction,
    ChangeNotice,
    ChangeOrder,
    ChangeOrderLine,
    ChangeRequest,
    EcoStatus,
    EcrStatus,
    EffectivityType,
)
from app.domains.ecm.schemas import ReleaseResult, RevisionCreated
from app.domains.ecm.service import _load_order, _next_number
from app.domains.identity.models import CCB_ROLES
from app.domains.knowledge.models import DocumentType, KnowledgeEmbedding
from app.domains.pdm.baselines import capture_baseline
from app.domains.pdm.mbom import derive_mbom
from app.domains.pdm.models import (
    BomEdge,
    BomType,
    ConfigurationBaseline,
    LifecycleState,
    Part,
    PartRevision,
)
from app.domains.pdm.revisioning import next_revision
from app.domains.pdm.service import get_where_used
from app.tools.registry import ToolError

logger = logging.getLogger(__name__)


async def release_change_order(
    session: AsyncSession, *, actor: Principal, number: str, commit: bool = True
) -> ReleaseResult:
    order = await _load_order(session, number)
    if order.status is not EcoStatus.DRAFT:
        raise ToolError(
            f"{order.number} is already {order.status.value.lower()} and cannot "
            "be released again."
        )

    request = (
        await session.execute(
            select(ChangeRequest).where(ChangeRequest.id == order.change_request_id)
        )
    ).scalar_one()
    if request.status not in (EcrStatus.APPROVED, EcrStatus.CONVERTED):
        raise ToolError(
            f"{order.number} cannot be released: its request {request.number} is "
            f"{request.status.value.lower()}, not approved."
        )
    if not order.lines:
        raise ToolError(f"{order.number} has no line items, so it changes nothing.")

    now = datetime.now(timezone.utc)
    result = ReleaseResult(change_order_number=order.number)

    # Group the work by assembly: one new revision per touched parent, however
    # many lines act on it.
    by_parent: dict = {}
    for line in order.lines:
        by_parent.setdefault(line.parent_part_id, []).append(line)

    # Price the released configuration immediately before it moves. The
    # snapshot is linked to the latest immutable configuration baseline, so
    # the post-release snapshot below forms an auditable before/after pair.
    affected_products = await _affected_products(session, list(by_parent))
    for product_number in affected_products:
        product = (
            await session.execute(
                select(Part).where(Part.part_number == product_number)
            )
        ).scalar_one()
        previous_baseline = (
            await session.execute(
                select(ConfigurationBaseline)
                .where(ConfigurationBaseline.root_part_id == product.id)
                .order_by(ConfigurationBaseline.captured_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if previous_baseline is not None:
            await capture_snapshot(
                session,
                product_number,
                1,
                captured_by=actor.user_id,
                baseline_id=previous_baseline.id,
                eco_id=order.id,
                commit=False,
            )

    new_revisions: dict = {}
    for parent_id, lines in by_parent.items():
        created, counts = await _revise_assembly(
            session, order=order, parent_id=parent_id, lines=lines, released_at=now,
            actor=actor,
        )
        new_revisions[parent_id] = created
        result.revisions_created.append(created["summary"])
        result.edges_added += counts["added"]
        result.edges_removed += counts["removed"]
        result.edges_modified += counts["modified"]

    await session.flush()

    # --- Baselines ---------------------------------------------------------
    for product in affected_products:
        name = f"{product} @ {order.number}"
        try:
            baseline = await capture_baseline(
                session,
                actor=actor,
                part_number=product,
                name=name,
                platform=product.split("-")[0],
                eco_id=order.id,
                notes=f"Configuration as released by {order.number}: {order.title}",
                commit=False,
            )
            result.baselines_captured.append(baseline.name)
            # The released EBOM revision is authoritative; rebuild the MBOM
            # before pricing the new baseline so the immutable delta reflects
            # the released manufacturing structure rather than stale lines.
            await derive_mbom(
                session,
                actor=actor,
                part_number=product,
                commit=False,
            )
            await capture_snapshot(
                session,
                product,
                1,
                captured_by=actor.user_id,
                baseline_id=baseline.id,
                eco_id=order.id,
                commit=False,
            )
        except ToolError as exc:
            result.warnings.append(f"Baseline for {product} not captured: {exc}")

    # --- Notice ------------------------------------------------------------
    notice = ChangeNotice(
        number=await _next_number(session, ChangeNotice, "ECN", now),
        change_order_id=order.id,
        body=_notice_body(order, request, result),
        recipients=_recipients(),
        issued_by=actor.user_id,
    )
    session.add(notice)
    result.notice_number = notice.number

    # --- Knowledge ---------------------------------------------------------
    result.knowledge_indexed = await _index_into_corpus(
        session, order=order, request=request, notice=notice, result=result
    )
    if not result.knowledge_indexed:
        result.warnings.append(
            "The change text was not added to the knowledge corpus; searching "
            "for the reason behind this change will not find it."
        )

    # --- Statuses ----------------------------------------------------------
    order.status = EcoStatus.RELEASED
    order.released_at = now
    order.released_by = actor.user_id
    if request.status is EcrStatus.APPROVED:
        request.status = EcrStatus.CONVERTED

    audit.record(
        session,
        actor=actor,
        action=AuditAction.TRANSITION,
        entity_type="ChangeOrder",
        entity_id=order.id,
        before={"status": EcoStatus.DRAFT.value},
        after={
            "status": EcoStatus.RELEASED.value,
            "revisions": [rev.model_dump() for rev in result.revisions_created],
            "notice": notice.number,
        },
        reason=order.disposition,
    )

    if commit:
        await session.commit()

    logger.info(
        "Released %s: %d revision(s), notice %s",
        order.number,
        len(result.revisions_created),
        notice.number,
    )
    return result


async def _revise_assembly(
    session: AsyncSession,
    *,
    order: ChangeOrder,
    parent_id,
    lines: list[ChangeOrderLine],
    released_at: datetime,
    actor: Principal,
) -> tuple[dict, dict]:
    """Create the next revision of one assembly and apply the order's lines."""
    part = (await session.execute(select(Part).where(Part.id == parent_id))).scalar_one()
    revisions = (
        await session.execute(
            select(PartRevision).where(PartRevision.part_id == parent_id)
        )
    ).scalars().all()
    if not revisions:
        raise ToolError(
            f"{part.part_number} has no revision to supersede. Create an initial "
            "one before changing it."
        )

    released = [rev for rev in revisions if rev.lifecycle_state is LifecycleState.RELEASED]
    previous = max(
        released or revisions,
        key=lambda rev: (rev.released_at or rev.created_at),
    )

    new_rev = PartRevision(
        part_id=parent_id,
        revision=next_revision(previous.revision),
        lifecycle_state=LifecycleState.RELEASED,
        released_at=(
            datetime.combine(order.effective_date, datetime.min.time(), timezone.utc)
            if order.effectivity_type is EffectivityType.DATE and order.effective_date
            else released_at
        ),
        released_by=actor.user_id,
        created_by_eco_id=order.id,
        change_summary=f"{order.number}: {order.title}",
    )
    session.add(new_rev)
    await session.flush()
    previous.superseded_by_id = new_rev.id

    # Carry the existing structure forward untouched, then edit the copy.
    existing = (
        await session.execute(
            select(BomEdge).where(
                BomEdge.parent_revision_id == previous.id,
                BomEdge.bom_type == BomType.EBOM,
            )
        )
    ).scalars().all()

    carried: dict = {}
    for edge in existing:
        clone = BomEdge(
            parent_revision_id=new_rev.id,
            child_part_id=edge.child_part_id,
            child_revision_id=edge.child_revision_id,
            bom_type=BomType.EBOM,
            quantity=edge.quantity,
            unit_of_measure=edge.unit_of_measure,
            find_number=edge.find_number,
            reference_designator=edge.reference_designator,
            effective_from=edge.effective_from,
            effective_to=edge.effective_to,
            effective_from_serial=edge.effective_from_serial,
            # Preserved: the line was introduced by whatever change introduced
            # it, not by this one.
            eco_in_id=edge.eco_in_id,
            notes=edge.notes,
        )
        session.add(clone)
        carried[edge.child_part_id] = clone
    await session.flush()

    counts = {"added": 0, "removed": 0, "modified": 0}
    for line in lines:
        if line.action is ChangeAction.REVISE_ATTRIBUTES:
            # The revision bump itself is the change; structure is untouched.
            continue

        if line.action is ChangeAction.ADD_COMPONENT:
            session.add(
                _new_edge(order, new_rev, line.child_part_id, line, counts)
            )
            counts["added"] += 1
            continue

        target = carried.get(line.child_part_id)
        if target is None:
            raise ToolError(
                f"{order.number} line {line.sequence}: {part.part_number} does "
                "not currently contain that component, so it cannot be "
                f"{line.action.value.lower()}d."
            )

        if line.action is ChangeAction.REMOVE_COMPONENT:
            await session.delete(target)
            counts["removed"] += 1
        elif line.action is ChangeAction.CHANGE_QUANTITY:
            target.quantity = line.quantity
            target.eco_in_id = order.id
            target.notes = line.notes or target.notes
            counts["modified"] += 1
        elif line.action is ChangeAction.REPLACE_COMPONENT:
            await session.delete(target)
            replacement = _new_edge(
                order, new_rev, line.new_child_part_id, line, counts
            )
            # Keep the position the old component occupied unless told otherwise.
            replacement.find_number = line.find_number or target.find_number
            replacement.quantity = (
                line.quantity if line.quantity is not None else target.quantity
            )
            session.add(replacement)
            counts["removed"] += 1
            counts["added"] += 1

    await session.flush()

    audit.record(
        session,
        actor=actor,
        action=AuditAction.CREATE,
        entity_type="PartRevision",
        entity_id=new_rev.id,
        before={"revision": previous.revision},
        after={"revision": new_rev.revision, "eco": order.number},
        reason=order.title,
    )

    return (
        {
            "revision": new_rev,
            "summary": RevisionCreated(
                part_number=part.part_number,
                from_revision=previous.revision,
                to_revision=new_rev.revision,
            ),
        },
        counts,
    )


def _new_edge(
    order: ChangeOrder, parent_rev: PartRevision, child_id, line, counts
) -> BomEdge:
    return BomEdge(
        parent_revision_id=parent_rev.id,
        child_part_id=child_id,
        bom_type=BomType.EBOM,
        quantity=line.quantity if line.quantity is not None else 1,
        find_number=line.find_number,
        # Serial-break effectivity is recorded on the line so the shop floor can
        # see where the cut is; date effectivity is carried by the revision's
        # release date instead.
        effective_from_serial=(
            order.effective_serial
            if order.effectivity_type is EffectivityType.SERIAL
            else None
        ),
        eco_in_id=order.id,
        notes=line.notes,
    )


async def _affected_products(session: AsyncSession, parent_ids: list) -> list[str]:
    """Finished products sitting above the assemblies this order revises."""
    products: set[str] = set()
    for parent_id in parent_ids:
        part_number = (
            await session.execute(
                select(Part.part_number).where(Part.id == parent_id)
            )
        ).scalar_one()
        used = await get_where_used(session, part_number)
        if used.top_level_products:
            products.update(used.top_level_products)
        else:
            # Nothing contains it, so the assembly is itself the product.
            products.add(part_number)
    return sorted(products)


def _notice_body(
    order: ChangeOrder, request: ChangeRequest, result: ReleaseResult
) -> str:
    revisions = "; ".join(
        f"{rev.part_number} {rev.from_revision} -> {rev.to_revision}"
        for rev in result.revisions_created
    )
    effectivity = {
        EffectivityType.ASAP: "immediately",
        EffectivityType.DATE: f"from {order.effective_date}",
        EffectivityType.SERIAL: f"from serial {order.effective_serial}",
    }[order.effectivity_type]

    return (
        f"{order.number} [{order.title}] is released and effective {effectivity}. "
        f"Raised as {request.number}: {request.problem_statement} "
        f"Disposition: {order.disposition} "
        f"Revisions issued: {revisions}. "
        "Configurations superseded by this notice are obsolete and must not be "
        "built to."
    )


def _recipients() -> list[str]:
    """Who has to be told.

    Every board seat, plus the contract manufacturer, who is building to the
    configuration this notice supersedes and is the party most damaged by not
    hearing about it.
    """
    return [role.value for role in CCB_ROLES] + ["contract-manufacturer"]


async def _index_into_corpus(
    session: AsyncSession,
    *,
    order: ChangeOrder,
    request: ChangeRequest,
    notice: ChangeNotice,
    result: ReleaseResult,
) -> bool:
    """Make the reason for this change findable by semantic search."""
    text = (
        f"{order.number} [{order.title}]: {order.disposition} "
        f"Raised as {request.number} — {request.problem_statement} "
        f"Proposed: {request.proposed_solution} "
        f"Revisions: "
        + "; ".join(
            f"{rev.part_number} {rev.from_revision}->{rev.to_revision}"
            for rev in result.revisions_created
        )
        + f". Notice {notice.number}."
    )

    provider = get_embedding_provider()
    try:
        vector = await provider.embed_one(text)
    except Exception as exc:  # noqa: BLE001 - the release must not fail for this
        # Indexing is valuable but not part of the configuration record. Losing
        # the whole release because an embedding call timed out would be a much
        # worse outcome than a corpus that is one document behind.
        logger.warning("Could not embed %s for the knowledge corpus: %s", order.number, exc)
        return False

    first_line = order.lines[0] if order.lines else None
    session.add(
        KnowledgeEmbedding(
            embedding=vector,
            related_part_id=first_line.parent_part_id if first_line else None,
            document_type=DocumentType.ECO,
            text_content=text,
            source_ref=order.number,
        )
    )
    return True
