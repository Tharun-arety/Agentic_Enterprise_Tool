"""The engineering change workflow, as an explicit state machine.

Transitions live in `_ECR_TRANSITIONS` and are checked at the service layer.
Encoding them as data rather than as scattered `if` statements means an illegal
move — approving a draft nobody submitted, releasing an order whose request was
rejected — fails with a message naming what was and was not allowed, instead of
succeeding quietly and leaving the record incoherent.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import audit
from app.core.audit import AuditAction
from app.core.principal import Principal
from app.domains.ecm.impact import assess
from app.domains.ecm.models import (
    ChangeAction,
    ChangeAffectedItem,
    ChangeBoardReview,
    ChangeNotice,
    ChangeOrder,
    ChangeOrderLine,
    ChangeOrigin,
    ChangePriority,
    ChangeRequest,
    EcoStatus,
    EcrStatus,
    EffectivityType,
    ImpactAssessment,
    ReviewDecision,
)
from app.domains.ecm.schemas import (
    ChangeBoardReviewOut,
    ChangeNoticeOut,
    ChangeOrderLineIn,
    ChangeOrderLineOut,
    ChangeOrderOut,
    ChangeRequestOut,
    ImpactAssessmentOut,
    ImpactFindings,
    QuorumStatus,
)
from app.domains.identity.models import CCB_ROLES, Role
from app.domains.pdm.models import Part
from app.tools.registry import ToolError

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# State machine
# --------------------------------------------------------------------------

_ECR_TRANSITIONS: dict[EcrStatus, set[EcrStatus]] = {
    EcrStatus.DRAFT: {EcrStatus.SUBMITTED, EcrStatus.CANCELLED},
    # Review opens on the first vote, so submission leads straight into it.
    EcrStatus.SUBMITTED: {EcrStatus.UNDER_REVIEW, EcrStatus.CANCELLED},
    EcrStatus.UNDER_REVIEW: {
        EcrStatus.APPROVED,
        EcrStatus.REJECTED,
        EcrStatus.CANCELLED,
    },
    EcrStatus.APPROVED: {EcrStatus.CONVERTED, EcrStatus.CANCELLED},
    # Terminal.
    EcrStatus.REJECTED: set(),
    EcrStatus.CONVERTED: set(),
    EcrStatus.CANCELLED: set(),
}


def _require_transition(current: EcrStatus, target: EcrStatus) -> None:
    allowed = _ECR_TRANSITIONS[current]
    if target not in allowed:
        options = ", ".join(sorted(state.value for state in allowed)) or "nothing"
        raise ToolError(
            f"A change request that is {current.value.lower()} cannot become "
            f"{target.value.lower()}. From here it can only become: {options}."
        )


# --------------------------------------------------------------------------
# Numbering
# --------------------------------------------------------------------------


async def _next_number(session: AsyncSession, model, prefix: str, when: datetime) -> str:
    """Allocate the next `PREFIX-YY-NNN` for the year.

    Read-then-write, so two concurrent callers can pick the same number. The
    unique constraint on the column turns that into a loud failure rather than
    a duplicate; at this volume that is the right trade against a sequence per
    prefix per year.
    """
    stem = f"{prefix}-{when:%y}-"
    highest = (
        await session.execute(
            select(func.max(model.number)).where(model.number.like(f"{stem}%"))
        )
    ).scalar_one_or_none()
    counter = int(highest.rsplit("-", 1)[1]) + 1 if highest else 1
    return f"{stem}{counter:03d}"


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def evaluate_quorum(request: ChangeRequest) -> QuorumStatus:
    """Whether the board has said enough for a decision to carry.

    Every seat must vote. A rejection sinks the change; a request for
    information blocks it without sinking it, because the board cannot rule on
    what it has not been told; an abstention is a seat with no stake saying so,
    and neither blocks nor endorses.
    """
    required = [role.value for role in CCB_ROLES]
    by_seat = {review.seat: review for review in request.reviews}

    voted = [seat for seat in required if seat in by_seat]
    missing = [seat for seat in required if seat not in by_seat]
    rejecting = [
        seat
        for seat in voted
        if by_seat[seat].decision is ReviewDecision.REJECT
    ]
    blocking = [
        seat
        for seat in voted
        if by_seat[seat].decision is ReviewDecision.REQUEST_INFO
    ]

    if rejecting:
        verdict = "rejected"
    elif blocking:
        verdict = "blocked"
    elif not missing:
        verdict = "approved"
    else:
        verdict = "incomplete"

    return QuorumStatus(
        required_seats=required,
        voted_seats=voted,
        missing_seats=missing,
        rejecting_seats=rejecting,
        blocking_seats=blocking,
        satisfied=not missing,
        verdict=verdict,
    )


async def _load_request(session: AsyncSession, number: str) -> ChangeRequest:
    request = (
        await session.execute(
            select(ChangeRequest)
            .where(ChangeRequest.number == number.strip().upper())
            .options(
                selectinload(ChangeRequest.affected_items),
                selectinload(ChangeRequest.reviews),
                selectinload(ChangeRequest.assessments),
            )
        )
    ).scalar_one_or_none()
    if request is None:
        known = (
            await session.execute(
                select(ChangeRequest.number).order_by(ChangeRequest.number)
            )
        ).scalars().all()
        raise ToolError(
            f"No change request {number!r}. Known: {', '.join(known)}"
            if known
            else f"No change request {number!r}, and none have been raised yet."
        )
    return request


async def _to_out(session: AsyncSession, request: ChangeRequest) -> ChangeRequestOut:
    part_numbers = (
        await session.execute(
            select(Part.part_number)
            .join(ChangeAffectedItem, ChangeAffectedItem.part_id == Part.id)
            .where(ChangeAffectedItem.change_request_id == request.id)
            .order_by(Part.part_number)
        )
    ).scalars().all()

    latest = request.assessments[-1] if request.assessments else None
    return ChangeRequestOut(
        id=request.id,
        number=request.number,
        title=request.title,
        problem_statement=request.problem_statement,
        proposed_solution=request.proposed_solution,
        preliminary_impact=request.preliminary_impact,
        originator_label=request.originator_label,
        origin=request.origin,
        priority=request.priority,
        status=request.status,
        created_at=request.created_at,
        submitted_at=request.submitted_at,
        decided_at=request.decided_at,
        affected_part_numbers=list(part_numbers),
        reviews=[ChangeBoardReviewOut.model_validate(r) for r in request.reviews],
        quorum=evaluate_quorum(request),
        latest_assessment=(
            ImpactAssessmentOut(
                id=latest.id,
                generated_at=latest.generated_at,
                generated_by=latest.generated_by,
                summary=latest.summary,
                findings=ImpactFindings.model_validate(latest.findings),
            )
            if latest
            else None
        ),
    )


async def get_change_request(session: AsyncSession, number: str) -> ChangeRequestOut:
    return await _to_out(session, await _load_request(session, number))


async def list_change_requests(
    session: AsyncSession,
    *,
    status: str | None = None,
    priority: str | None = None,
    limit: int = 50,
) -> list[ChangeRequestOut]:
    """Change requests, newest first, optionally narrowed.

    Keyword-only past `session` on purpose. `priority` was inserted between the
    existing `status` and `limit`, and the one positional caller silently
    re-bound its limit of 50 onto it — the change board screen started
    reporting "Unknown priority 50". Naming the arguments makes inserting
    another filter a non-event.
    """
    query = (
        select(ChangeRequest)
        .order_by(ChangeRequest.created_at.desc())
        .limit(limit)
        .options(
            selectinload(ChangeRequest.affected_items),
            selectinload(ChangeRequest.reviews),
            selectinload(ChangeRequest.assessments),
        )
    )
    if status:
        try:
            query = query.where(ChangeRequest.status == EcrStatus(status))
        except ValueError:
            options = ", ".join(state.value for state in EcrStatus)
            raise ToolError(f"Unknown status {status!r}. One of: {options}") from None
    # Filtering by priority was missing, so "which changes are urgent" had no
    # query behind it and the caller had to pull every request and sort it out.
    if priority:
        try:
            query = query.where(ChangeRequest.priority == ChangePriority(priority))
        except ValueError:
            options = ", ".join(level.value for level in ChangePriority)
            raise ToolError(f"Unknown priority {priority!r}. One of: {options}") from None
    rows = (await session.execute(query)).scalars().all()
    return [await _to_out(session, row) for row in rows]


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


async def create_change_request(
    session: AsyncSession,
    *,
    actor: Principal,
    title: str,
    problem_statement: str,
    proposed_solution: str,
    affected_part_numbers: list[str],
    origin: ChangeOrigin = ChangeOrigin.RND,
    priority: ChangePriority = ChangePriority.NORMAL,
    preliminary_impact: str | None = None,
    commit: bool = True,
) -> ChangeRequestOut:
    """Raise an ECR in draft, with an impact assessment already attached."""
    wanted = [number.strip().upper() for number in affected_part_numbers]
    parts = (
        await session.execute(select(Part).where(Part.part_number.in_(wanted)))
    ).scalars().all()
    found = {part.part_number for part in parts}
    if missing := sorted(set(wanted) - found):
        raise ToolError(
            f"These are not in the part master: {', '.join(missing)}. A change "
            "request has to name items that exist."
        )

    now = datetime.now(timezone.utc)
    request = ChangeRequest(
        number=await _next_number(session, ChangeRequest, "ECR", now),
        title=title.strip(),
        problem_statement=problem_statement.strip(),
        proposed_solution=proposed_solution.strip(),
        preliminary_impact=preliminary_impact,
        originator_id=actor.user_id,
        originator_label=actor.label,
        origin=origin,
        priority=priority,
        status=EcrStatus.DRAFT,
    )
    session.add(request)
    await session.flush()

    for part in parts:
        session.add(
            ChangeAffectedItem(change_request_id=request.id, part_id=part.id)
        )
    await session.flush()

    # Assessed at creation rather than on demand: the point of the process is
    # that nobody reads the request without also seeing what it reaches.
    findings, summary = await assess(session, sorted(found))
    session.add(
        ImpactAssessment(
            change_request_id=request.id,
            generated_by=actor.label,
            summary=summary,
            findings=findings.model_dump(mode="json"),
        )
    )

    audit.record(
        session,
        actor=actor,
        action=AuditAction.CREATE,
        entity_type="ChangeRequest",
        entity_id=request.id,
        after={
            "number": request.number,
            "title": request.title,
            "affected": sorted(found),
        },
    )
    if commit:
        await session.commit()

    logger.info("Raised %s over %s", request.number, ", ".join(sorted(found)))
    return await _to_out(session, await _load_request(session, request.number))


async def reassess(
    session: AsyncSession, *, actor: Principal, number: str, commit: bool = True
) -> ImpactAssessmentOut:
    """Recompute the impact and attach a fresh assessment.

    A new row rather than an update: the board voted against a specific
    assessment, and overwriting it would erase what they were shown.
    """
    request = await _load_request(session, number)
    part_numbers = (
        await session.execute(
            select(Part.part_number)
            .join(ChangeAffectedItem, ChangeAffectedItem.part_id == Part.id)
            .where(ChangeAffectedItem.change_request_id == request.id)
        )
    ).scalars().all()

    findings, summary = await assess(session, sorted(part_numbers))
    assessment = ImpactAssessment(
        change_request_id=request.id,
        generated_by=actor.label,
        summary=summary,
        findings=findings.model_dump(mode="json"),
    )
    session.add(assessment)
    await session.flush()
    if commit:
        await session.commit()

    return ImpactAssessmentOut(
        id=assessment.id,
        generated_at=assessment.generated_at,
        generated_by=assessment.generated_by,
        summary=summary,
        findings=findings,
    )


async def submit_change_request(
    session: AsyncSession, *, actor: Principal, number: str, commit: bool = True
) -> ChangeRequestOut:
    request = await _load_request(session, number)
    _require_transition(request.status, EcrStatus.SUBMITTED)
    if not request.affected_items:
        raise ToolError(
            f"{request.number} names no affected items. There is nothing for the "
            "board to assess."
        )

    request.status = EcrStatus.SUBMITTED
    request.submitted_at = datetime.now(timezone.utc)
    audit.record(
        session,
        actor=actor,
        action=AuditAction.TRANSITION,
        entity_type="ChangeRequest",
        entity_id=request.id,
        before={"status": EcrStatus.DRAFT.value},
        after={"status": EcrStatus.SUBMITTED.value},
    )
    if commit:
        await session.commit()
    return await _to_out(session, request)


def _seat_for(actor: Principal, requested: str | None) -> str:
    """Which board seat this person is voting as."""
    held = [role.value for role in CCB_ROLES if role.value in actor.roles]
    if Role.ADMIN.value in actor.roles and not held:
        held = [role.value for role in CCB_ROLES]

    if requested:
        if requested not in held:
            raise ToolError(
                f"{actor.label} does not hold the {requested!r} seat. Seats held: "
                f"{', '.join(held) or 'none'}."
            )
        return requested
    if not held:
        raise ToolError(
            f"{actor.label} holds no Change Control Board seat, so cannot vote. "
            f"Seats are: {', '.join(role.value for role in CCB_ROLES)}."
        )
    if len(held) > 1:
        raise ToolError(
            f"{actor.label} holds several board seats ({', '.join(held)}). Say "
            "which one this vote is cast as."
        )
    return held[0]


async def record_review(
    session: AsyncSession,
    *,
    actor: Principal,
    number: str,
    decision: ReviewDecision,
    comment: str | None = None,
    seat: str | None = None,
    commit: bool = True,
) -> ChangeRequestOut:
    """Cast one seat's vote, and settle the request if the board is complete."""
    request = await _load_request(session, number)
    if request.status is EcrStatus.SUBMITTED:
        _require_transition(request.status, EcrStatus.UNDER_REVIEW)
        request.status = EcrStatus.UNDER_REVIEW
    if request.status is not EcrStatus.UNDER_REVIEW:
        raise ToolError(
            f"{request.number} is {request.status.value.lower()} and is not open "
            "for review."
        )

    voting_seat = _seat_for(actor, seat)
    existing = next((r for r in request.reviews if r.seat == voting_seat), None)
    if existing is not None:
        raise ToolError(
            f"The {voting_seat!r} seat has already ruled on {request.number} "
            f"({existing.decision.value}). A vote is not revised; raise a new "
            "request if the position has changed."
        )

    review = ChangeBoardReview(
        change_request_id=request.id,
        seat=voting_seat,
        reviewer_id=actor.user_id,
        reviewer_label=actor.label,
        decision=decision,
        comment=comment,
    )
    session.add(review)
    request.reviews.append(review)
    await session.flush()

    quorum = evaluate_quorum(request)
    if quorum.verdict == "rejected":
        request.status = EcrStatus.REJECTED
        request.decided_at = datetime.now(timezone.utc)
    elif quorum.verdict == "approved":
        request.status = EcrStatus.APPROVED
        request.decided_at = datetime.now(timezone.utc)

    audit.record(
        session,
        actor=actor,
        action=(
            AuditAction.APPROVE
            if decision is ReviewDecision.APPROVE
            else AuditAction.REJECT
        ),
        entity_type="ChangeRequest",
        entity_id=request.id,
        after={
            "seat": voting_seat,
            "decision": decision.value,
            "quorum": quorum.verdict,
            "status": request.status.value,
        },
        reason=comment,
    )
    if commit:
        await session.commit()

    logger.info(
        "%s: %s voted %s (quorum: %s)",
        request.number,
        voting_seat,
        decision.value,
        quorum.verdict,
    )
    return await _to_out(session, request)


# --------------------------------------------------------------------------
# Change orders
# --------------------------------------------------------------------------


async def _load_order(session: AsyncSession, number: str) -> ChangeOrder:
    order = (
        await session.execute(
            select(ChangeOrder)
            .where(ChangeOrder.number == number.strip().upper())
            .options(
                selectinload(ChangeOrder.lines),
                selectinload(ChangeOrder.notices).selectinload(
                    ChangeNotice.acknowledgements
                ),
            )
        )
    ).scalar_one_or_none()
    if order is None:
        raise ToolError(f"No change order {number!r}.")
    return order


async def _order_out(session: AsyncSession, order: ChangeOrder) -> ChangeOrderOut:
    numbers: dict[uuid.UUID, str] = dict(
        (
            await session.execute(
                select(Part.id, Part.part_number).where(
                    Part.id.in_(
                        [line.parent_part_id for line in order.lines]
                        + [line.child_part_id for line in order.lines if line.child_part_id]
                        + [
                            line.new_child_part_id
                            for line in order.lines
                            if line.new_child_part_id
                        ]
                    )
                )
            )
        ).all()
    )
    request_number = (
        await session.execute(
            select(ChangeRequest.number).where(
                ChangeRequest.id == order.change_request_id
            )
        )
    ).scalar_one()

    return ChangeOrderOut(
        id=order.id,
        number=order.number,
        title=order.title,
        change_request_number=request_number,
        disposition=order.disposition,
        effectivity_type=order.effectivity_type,
        effective_date=order.effective_date,
        effective_serial=order.effective_serial,
        status=order.status,
        created_at=order.created_at,
        released_at=order.released_at,
        lines=[
            ChangeOrderLineOut(
                sequence=line.sequence,
                action=line.action,
                parent_part_number=numbers.get(line.parent_part_id, "?"),
                child_part_number=numbers.get(line.child_part_id) if line.child_part_id else None,
                new_child_part_number=(
                    numbers.get(line.new_child_part_id) if line.new_child_part_id else None
                ),
                quantity=float(line.quantity) if line.quantity is not None else None,
                find_number=line.find_number,
                notes=line.notes,
            )
            for line in order.lines
        ],
        notices=[
            ChangeNoticeOut(
                number=notice.number,
                body=notice.body,
                recipients=list(notice.recipients),
                issued_at=notice.issued_at,
                acknowledged_by=[ack.recipient for ack in notice.acknowledgements],
            )
            for notice in order.notices
        ],
    )


async def create_change_order(
    session: AsyncSession,
    *,
    actor: Principal,
    change_request_number: str,
    title: str,
    disposition: str,
    lines: list[ChangeOrderLineIn],
    effectivity_type: EffectivityType = EffectivityType.ASAP,
    effective_date: date | None = None,
    effective_serial: str | None = None,
    commit: bool = True,
) -> ChangeOrderOut:
    """Author the order that carries an approved request out."""
    request = await _load_request(session, change_request_number)
    if request.status is not EcrStatus.APPROVED:
        raise ToolError(
            f"{request.number} is {request.status.value.lower()}. Only an "
            "approved request can become a change order — that approval is the "
            "board's authority for the change."
        )
    if effectivity_type is EffectivityType.DATE and effective_date is None:
        raise ToolError("Date effectivity needs an effective date.")
    if effectivity_type is EffectivityType.SERIAL and not effective_serial:
        raise ToolError("Serial effectivity needs a serial number to start from.")

    now = datetime.now(timezone.utc)
    order = ChangeOrder(
        number=await _next_number(session, ChangeOrder, "ECO", now),
        title=title.strip(),
        change_request_id=request.id,
        disposition=disposition.strip(),
        effectivity_type=effectivity_type,
        effective_date=effective_date,
        effective_serial=effective_serial,
        status=EcoStatus.DRAFT,
    )
    session.add(order)
    await session.flush()

    for index, line in enumerate(lines, start=1):
        session.add(await _build_line(session, order.id, index * 10, line))
    await session.flush()

    audit.record(
        session,
        actor=actor,
        action=AuditAction.CREATE,
        entity_type="ChangeOrder",
        entity_id=order.id,
        after={"number": order.number, "from": request.number, "lines": len(lines)},
    )
    if commit:
        await session.commit()
    return await _order_out(session, await _load_order(session, order.number))


async def _build_line(
    session: AsyncSession, order_id: uuid.UUID, sequence: int, line: ChangeOrderLineIn
) -> ChangeOrderLine:
    async def part_id(part_number: str | None, label: str) -> uuid.UUID | None:
        if not part_number:
            return None
        found = (
            await session.execute(
                select(Part.id).where(Part.part_number == part_number.strip().upper())
            )
        ).scalar_one_or_none()
        if found is None:
            raise ToolError(f"{label} {part_number!r} is not in the part master.")
        return found

    parent = await part_id(line.parent_part_number, "Parent assembly")
    assert parent is not None  # part_id only returns None for a falsy input

    if line.action in (
        ChangeAction.ADD_COMPONENT,
        ChangeAction.REMOVE_COMPONENT,
        ChangeAction.CHANGE_QUANTITY,
        ChangeAction.REPLACE_COMPONENT,
    ) and not line.child_part_number:
        raise ToolError(f"{line.action.value} needs a component to act on.")
    if line.action is ChangeAction.REPLACE_COMPONENT and not line.new_child_part_number:
        raise ToolError("Replace needs the component that goes in.")
    if line.action in (ChangeAction.ADD_COMPONENT, ChangeAction.CHANGE_QUANTITY) and (
        line.quantity is None
    ):
        raise ToolError(f"{line.action.value} needs a quantity.")

    return ChangeOrderLine(
        change_order_id=order_id,
        sequence=sequence,
        action=line.action,
        parent_part_id=parent,
        child_part_id=await part_id(line.child_part_number, "Component"),
        new_child_part_id=await part_id(line.new_child_part_number, "Replacement"),
        quantity=line.quantity,
        find_number=line.find_number,
        notes=line.notes,
    )


async def get_change_order(session: AsyncSession, number: str) -> ChangeOrderOut:
    return await _order_out(session, await _load_order(session, number))
