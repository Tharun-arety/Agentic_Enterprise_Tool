"""The engineering change workflow: ECR, CCB quorum, ECO, release, ECN."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.ecm import service
from app.domains.ecm.models import (
    ChangeAction,
    ChangeNotice,
    EcoStatus,
    EcrStatus,
    EffectivityType,
    ReviewDecision,
)
from app.domains.ecm.release import release_change_order
from app.domains.ecm.schemas import ChangeOrderLineIn
from app.domains.identity.models import Role
from app.domains.knowledge.models import KnowledgeEmbedding
from app.domains.pdm.models import BomType, Part, PartRevision
from app.domains.pdm.service import get_bom_structure
from app.tools.registry import ToolError
from tests.conftest import principal_for
from tests.test_pdm_structure import flatten, link, make_part

pytestmark = pytest.mark.db


@pytest.fixture
async def tree(session: AsyncSession):
    """PRODUCT -> MODULE -> {OLD-PART, WIDGET}, plus a spare replacement part."""
    from app.domains.pdm.models import PartClass

    product, product_rev = await make_part(
        session, "EC-PRD-100", part_class=PartClass.ASSEMBLY
    )
    module, module_rev = await make_part(
        session, "EC-MOD-200", part_class=PartClass.ASSEMBLY
    )
    old, _ = await make_part(session, "EC-OLD-300")
    widget, _ = await make_part(session, "EC-WID-400")
    replacement, _ = await make_part(session, "EC-NEW-301")
    await link(session, product_rev, module, quantity="1", find_number="100")
    await link(session, module_rev, old, quantity="4", find_number="110")
    await link(session, module_rev, widget, quantity="1", find_number="120")
    await session.commit()
    return {
        "product": product,
        "module": module,
        "module_rev": module_rev,
        "old": old,
        "widget": widget,
        "replacement": replacement,
    }


@pytest.fixture
async def board(user_factory):
    """One user per Change Control Board seat."""
    from app.domains.identity.models import CCB_ROLES

    return {
        role.value: principal_for(await user_factory(role)) for role in CCB_ROLES
    }


async def raise_ecr(session: AsyncSession, actor, parts=("EC-OLD-300",)):
    return await service.create_change_request(
        session,
        actor=actor,
        title="Replace the bonded bed with a freeze-cast one",
        problem_statement="The bonded geometry limits conjugate heat transfer.",
        proposed_solution="Move to freeze-cast lamellar channels.",
        affected_part_numbers=list(parts),
    )


# --------------------------------------------------------------------------
# Raising
# --------------------------------------------------------------------------


async def test_a_new_request_is_numbered_and_assessed(
    session: AsyncSession, tree, user_factory
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)

    year = datetime.now(timezone.utc).strftime("%y")
    assert ecr.number == f"ECR-{year}-001"
    assert ecr.status is EcrStatus.DRAFT
    assert ecr.affected_part_numbers == ["EC-OLD-300"]

    # Assessed at creation, so nobody reads the request without its impact.
    assert ecr.latest_assessment is not None
    findings = ecr.latest_assessment.findings
    assert {a.part_number for a in findings.affected_assemblies} == {
        "EC-MOD-200",
        "EC-PRD-100",
    }
    assert [p.part_number for p in findings.affected_products] == ["EC-PRD-100"]


async def test_numbering_increments_within_the_year(
    session: AsyncSession, tree, user_factory
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    first = await raise_ecr(session, engineer)
    second = await raise_ecr(session, engineer)
    assert int(second.number.rsplit("-", 1)[1]) == int(first.number.rsplit("-", 1)[1]) + 1


async def test_a_request_naming_an_unknown_part_is_refused(
    session: AsyncSession, tree, user_factory
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    with pytest.raises(ToolError, match="not in the part master"):
        await raise_ecr(session, engineer, parts=("NOPE-000",))


async def test_the_assessment_flags_test_evidence_that_would_need_repeating(
    session: AsyncSession, tree, user_factory
) -> None:
    """Evidence is found through the as-built record, not through today's BOM."""
    from app.core.principal import SYSTEM_PRINCIPAL
    from app.domains.qms.models import LabTestRecord, Unit
    from app.domains.qms.service import build_unit

    # A physical module was built containing the part the change affects, and
    # measured.
    await build_unit(
        session,
        actor=SYSTEM_PRINCIPAL,
        serial_number="EC-M-001",
        part_number="EC-MOD-200",
        built_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
    )
    unit = (
        await session.execute(select(Unit).where(Unit.serial_number == "EC-M-001"))
    ).scalar_one()
    session.add(
        LabTestRecord(
            unit_id=unit.id,
            recorded_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
            temperature_span_delta_K=15.0,
            pressure_drop_mbar=840.0,
            magnetization_cycles_hz=2.5,
            cooling_capacity_W=980.0,
        )
    )
    await session.commit()

    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)
    evidence = ecr.latest_assessment.findings.revalidation_required
    assert [e.serial_number for e in evidence] == ["EC-M-001"]
    assert "re-validating" in ecr.latest_assessment.summary


# --------------------------------------------------------------------------
# State machine
# --------------------------------------------------------------------------


async def test_a_draft_cannot_be_reviewed_before_it_is_submitted(
    session: AsyncSession, tree, user_factory, board
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)

    with pytest.raises(ToolError, match="not open for review"):
        await service.record_review(
            session,
            actor=board[Role.QUALITY.value],
            number=ecr.number,
            decision=ReviewDecision.APPROVE,
        )


async def test_a_rejected_request_is_terminal(
    session: AsyncSession, tree, user_factory, board
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)
    await service.submit_change_request(session, actor=engineer, number=ecr.number)
    await service.record_review(
        session,
        actor=board[Role.QUALITY.value],
        number=ecr.number,
        decision=ReviewDecision.REJECT,
        comment="Not while the qualification is open.",
    )

    with pytest.raises(ToolError, match="cannot become"):
        await service.submit_change_request(session, actor=engineer, number=ecr.number)


async def test_submitting_a_request_with_no_affected_items_is_refused(
    session: AsyncSession, tree, user_factory
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)
    request = await service._load_request(session, ecr.number)
    for item in list(request.affected_items):
        await session.delete(item)
    await session.commit()
    # The deleted rows are still in this session's identity map, and
    # `selectinload` will not overwrite an already-populated collection. In
    # production every request gets a fresh session; here that has to be forced,
    # or the guard is tested against a stale in-memory copy.
    session.expire_all()

    with pytest.raises(ToolError, match="names no affected items"):
        await service.submit_change_request(session, actor=engineer, number=ecr.number)


# --------------------------------------------------------------------------
# Quorum
# --------------------------------------------------------------------------


async def test_the_board_must_be_complete_before_a_request_carries(
    session: AsyncSession, tree, user_factory, board
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)
    await service.submit_change_request(session, actor=engineer, number=ecr.number)

    seats = list(board)
    for seat in seats[:-1]:
        result = await service.record_review(
            session,
            actor=board[seat],
            number=ecr.number,
            decision=ReviewDecision.APPROVE,
        )
        assert result.status is EcrStatus.UNDER_REVIEW
        assert result.quorum.verdict == "incomplete"

    final = await service.record_review(
        session,
        actor=board[seats[-1]],
        number=ecr.number,
        decision=ReviewDecision.APPROVE,
    )
    assert final.quorum.verdict == "approved"
    assert final.status is EcrStatus.APPROVED
    assert final.decided_at is not None


async def test_one_rejection_sinks_the_change(
    session: AsyncSession, tree, user_factory, board
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)
    await service.submit_change_request(session, actor=engineer, number=ecr.number)

    await service.record_review(
        session,
        actor=board[Role.SYSTEMS_ENGINEERING.value],
        number=ecr.number,
        decision=ReviewDecision.APPROVE,
    )
    result = await service.record_review(
        session,
        actor=board[Role.PROCUREMENT.value],
        number=ecr.number,
        decision=ReviewDecision.REJECT,
        comment="Sole-sourced with a 26-week lead time.",
    )
    # Rejected immediately: waiting for the remaining seats would be theatre.
    assert result.status is EcrStatus.REJECTED
    assert result.quorum.rejecting_seats == [Role.PROCUREMENT.value]


async def test_a_request_for_information_blocks_without_rejecting(
    session: AsyncSession, tree, user_factory, board
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)
    await service.submit_change_request(session, actor=engineer, number=ecr.number)

    for seat, decision in [
        (Role.SYSTEMS_ENGINEERING.value, ReviewDecision.APPROVE),
        (Role.QUALITY.value, ReviewDecision.REQUEST_INFO),
        (Role.MANUFACTURING.value, ReviewDecision.APPROVE),
        (Role.PROCUREMENT.value, ReviewDecision.APPROVE),
    ]:
        result = await service.record_review(
            session, actor=board[seat], number=ecr.number, decision=decision
        )

    assert result.quorum.verdict == "blocked"
    assert result.status is EcrStatus.UNDER_REVIEW
    assert result.quorum.blocking_seats == [Role.QUALITY.value]


async def test_an_abstention_neither_blocks_nor_endorses(
    session: AsyncSession, tree, user_factory, board
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)
    await service.submit_change_request(session, actor=engineer, number=ecr.number)

    for seat in board:
        decision = (
            ReviewDecision.ABSTAIN
            if seat == Role.PROCUREMENT.value
            else ReviewDecision.APPROVE
        )
        result = await service.record_review(
            session, actor=board[seat], number=ecr.number, decision=decision
        )
    assert result.status is EcrStatus.APPROVED


async def test_a_seat_votes_once(
    session: AsyncSession, tree, user_factory, board
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)
    await service.submit_change_request(session, actor=engineer, number=ecr.number)
    await service.record_review(
        session,
        actor=board[Role.QUALITY.value],
        number=ecr.number,
        decision=ReviewDecision.APPROVE,
    )
    with pytest.raises(ToolError, match="already ruled"):
        await service.record_review(
            session,
            actor=board[Role.QUALITY.value],
            number=ecr.number,
            decision=ReviewDecision.REJECT,
        )


async def test_someone_with_no_board_seat_cannot_vote(
    session: AsyncSession, tree, user_factory
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)
    await service.submit_change_request(session, actor=engineer, number=ecr.number)
    with pytest.raises(ToolError, match="no Change Control Board seat"):
        await service.record_review(
            session, actor=engineer, number=ecr.number, decision=ReviewDecision.APPROVE
        )


# --------------------------------------------------------------------------
# Change orders
# --------------------------------------------------------------------------


async def approve_ecr(session: AsyncSession, board, number: str) -> None:
    for seat in board:
        await service.record_review(
            session, actor=board[seat], number=number, decision=ReviewDecision.APPROVE
        )


@pytest.fixture
async def approved(session: AsyncSession, tree, user_factory, board):
    """A request that has genuinely cleared the board.

    Voted through rather than short-circuited: the downstream tests then start
    from a record the workflow actually produced, not one assembled behind its
    back. The forty-odd extra round trips this costs are free against the local
    server the suite runs on.
    """
    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)
    await service.submit_change_request(session, actor=engineer, number=ecr.number)
    await approve_ecr(session, board, ecr.number)
    return ecr, engineer


async def test_an_order_cannot_be_authored_from_an_unapproved_request(
    session: AsyncSession, tree, user_factory, board
) -> None:
    engineer = principal_for(await user_factory(Role.ENGINEER))
    ecr = await raise_ecr(session, engineer)
    with pytest.raises(ToolError, match="Only an approved request"):
        await service.create_change_order(
            session,
            actor=board[Role.SYSTEMS_ENGINEERING.value],
            change_request_number=ecr.number,
            title="Swap the bed",
            disposition="Replace on the next build.",
            lines=[
                ChangeOrderLineIn(
                    action=ChangeAction.REPLACE_COMPONENT,
                    parent_part_number="EC-MOD-200",
                    child_part_number="EC-OLD-300",
                    new_child_part_number="EC-NEW-301",
                    quantity=6,
                )
            ],
        )


async def test_date_effectivity_requires_a_date(
    session: AsyncSession, tree, approved, board
) -> None:
    ecr, _ = approved
    with pytest.raises(ToolError, match="needs an effective date"):
        await service.create_change_order(
            session,
            actor=board[Role.SYSTEMS_ENGINEERING.value],
            change_request_number=ecr.number,
            title="Swap the bed",
            disposition="Replace on the next build.",
            effectivity_type=EffectivityType.DATE,
            lines=[
                ChangeOrderLineIn(
                    action=ChangeAction.CHANGE_QUANTITY,
                    parent_part_number="EC-MOD-200",
                    child_part_number="EC-OLD-300",
                    quantity=6,
                )
            ],
        )


async def test_a_line_missing_its_quantity_is_refused(
    session: AsyncSession, tree, approved, board
) -> None:
    ecr, _ = approved
    with pytest.raises(ToolError, match="needs a quantity"):
        await service.create_change_order(
            session,
            actor=board[Role.SYSTEMS_ENGINEERING.value],
            change_request_number=ecr.number,
            title="Swap the bed",
            disposition="Replace on the next build.",
            lines=[
                ChangeOrderLineIn(
                    action=ChangeAction.CHANGE_QUANTITY,
                    parent_part_number="EC-MOD-200",
                    child_part_number="EC-OLD-300",
                )
            ],
        )


# --------------------------------------------------------------------------
# Release
# --------------------------------------------------------------------------


async def author_order(session, board, ecr_number, lines, **kwargs):
    return await service.create_change_order(
        session,
        actor=board[Role.SYSTEMS_ENGINEERING.value],
        change_request_number=ecr_number,
        title="Freeze-cast bed",
        disposition="Replace the bonded bed; qualification passed.",
        lines=lines,
        **kwargs,
    )


async def test_release_issues_a_new_revision_and_applies_the_lines(
    session: AsyncSession, tree, approved, board
) -> None:
    ecr, _ = approved
    eco = await author_order(
        session,
        board,
        ecr.number,
        [
            ChangeOrderLineIn(
                action=ChangeAction.REPLACE_COMPONENT,
                parent_part_number="EC-MOD-200",
                child_part_number="EC-OLD-300",
                new_child_part_number="EC-NEW-301",
                quantity=6,
            )
        ],
    )

    before = flatten((await get_bom_structure(session, "EC-PRD-100")).tree)
    assert before["EC-MOD-200"].revision == "A"
    assert "EC-OLD-300" in before

    result = await release_change_order(
        session, actor=board[Role.SYSTEMS_ENGINEERING.value], number=eco.number
    )

    assert [r.model_dump() for r in result.revisions_created] == [
        {"part_number": "EC-MOD-200", "from_revision": "A", "to_revision": "B"}
    ]
    after = flatten((await get_bom_structure(session, "EC-PRD-100")).tree)
    assert after["EC-MOD-200"].revision == "B"
    assert "EC-OLD-300" not in after
    assert after["EC-NEW-301"].quantity == 6
    # Carried forward untouched.
    assert after["EC-WID-400"].quantity == 1


async def test_the_parent_above_picks_up_the_new_revision_without_being_revised(
    session: AsyncSession, tree, approved, board
) -> None:
    """The payoff of binding an edge to a parent revision and a child *part*."""
    ecr, _ = approved
    eco = await author_order(
        session,
        board,
        ecr.number,
        [
            ChangeOrderLineIn(
                action=ChangeAction.CHANGE_QUANTITY,
                parent_part_number="EC-MOD-200",
                child_part_number="EC-OLD-300",
                quantity=9,
            )
        ],
    )
    result = await release_change_order(
        session, actor=board[Role.SYSTEMS_ENGINEERING.value], number=eco.number
    )

    # Only the module was revised.
    assert [r.part_number for r in result.revisions_created] == ["EC-MOD-200"]
    product_revisions = (
        await session.execute(
            select(PartRevision.revision)
            .join(Part, Part.id == PartRevision.part_id)
            .where(Part.part_number == "EC-PRD-100")
        )
    ).scalars().all()
    assert product_revisions == ["A"], "the product must not have been re-revised"

    # Yet exploding the product reaches the module's new revision.
    after = flatten((await get_bom_structure(session, "EC-PRD-100")).tree)
    assert after["EC-MOD-200"].revision == "B"
    assert after["EC-OLD-300"].quantity == 9


async def test_the_superseded_revision_keeps_its_own_structure(
    session: AsyncSession, tree, approved, board
) -> None:
    """A unit built to revision A still resolves to what it actually contains."""
    ecr, _ = approved
    eco = await author_order(
        session,
        board,
        ecr.number,
        [
            ChangeOrderLineIn(
                action=ChangeAction.REMOVE_COMPONENT,
                parent_part_number="EC-MOD-200",
                child_part_number="EC-OLD-300",
            )
        ],
    )
    await release_change_order(
        session, actor=board[Role.SYSTEMS_ENGINEERING.value], number=eco.number
    )

    old_rev = (
        await session.execute(
            select(PartRevision)
            .join(Part, Part.id == PartRevision.part_id)
            .where(Part.part_number == "EC-MOD-200", PartRevision.revision == "A")
        )
    ).scalar_one()
    await session.refresh(old_rev, ["child_edges"])
    # Count the two views separately. Releasing an order re-derives the
    # manufacturing bill, so a revision carries MBOM lines as well as EBOM
    # ones, and a bare `len(child_edges)` silently conflates them — it read 4
    # here and told you nothing about which view had gained a line.
    kept = [edge for edge in old_rev.child_edges if edge.bom_type is BomType.EBOM]
    assert len(kept) == 2, "revision A still contains both components"
    # The as-built manufacturing structure has to survive too: a unit built to
    # revision A was made to revision A's routing, not to the one that replaced it.
    manufacturing = [edge for edge in old_rev.child_edges if edge.bom_type is BomType.MBOM]
    assert len(manufacturing) == 2, "revision A keeps the MBOM it was built to"
    assert old_rev.superseded_by_id is not None


async def test_a_line_acting_on_a_component_that_is_not_there_is_refused(
    session: AsyncSession, tree, approved, board
) -> None:
    ecr, _ = approved
    eco = await author_order(
        session,
        board,
        ecr.number,
        [
            ChangeOrderLineIn(
                action=ChangeAction.REMOVE_COMPONENT,
                parent_part_number="EC-MOD-200",
                child_part_number="EC-NEW-301",  # never was in the module
            )
        ],
    )
    with pytest.raises(ToolError, match="does not currently contain"):
        await release_change_order(
            session, actor=board[Role.SYSTEMS_ENGINEERING.value], number=eco.number
        )


async def test_release_captures_a_baseline_and_issues_a_notice(
    session: AsyncSession, tree, approved, board
) -> None:
    ecr, _ = approved
    eco = await author_order(
        session,
        board,
        ecr.number,
        [
            ChangeOrderLineIn(
                action=ChangeAction.CHANGE_QUANTITY,
                parent_part_number="EC-MOD-200",
                child_part_number="EC-OLD-300",
                quantity=5,
            )
        ],
    )
    result = await release_change_order(
        session, actor=board[Role.SYSTEMS_ENGINEERING.value], number=eco.number
    )

    assert result.baselines_captured == [f"EC-PRD-100 @ {eco.number}"]
    assert result.notice_number is not None

    notice = (
        await session.execute(
            select(ChangeNotice).where(ChangeNotice.number == result.notice_number)
        )
    ).scalar_one()
    assert "contract-manufacturer" in notice.recipients
    assert eco.number in notice.body
    assert "EC-MOD-200 A -> B" in notice.body


async def test_release_indexes_the_change_into_the_knowledge_corpus(
    session: AsyncSession, tree, approved, board
) -> None:
    """The corpus populates itself from the transactional record."""
    ecr, _ = approved
    eco = await author_order(
        session,
        board,
        ecr.number,
        [
            ChangeOrderLineIn(
                action=ChangeAction.CHANGE_QUANTITY,
                parent_part_number="EC-MOD-200",
                child_part_number="EC-OLD-300",
                quantity=5,
            )
        ],
    )
    result = await release_change_order(
        session, actor=board[Role.SYSTEMS_ENGINEERING.value], number=eco.number
    )
    assert result.knowledge_indexed

    indexed = (
        await session.execute(
            select(KnowledgeEmbedding).where(
                KnowledgeEmbedding.source_ref == eco.number
            )
        )
    ).scalar_one()
    assert "freeze-cast" in indexed.text_content.lower()


async def test_release_marks_the_order_released_and_the_request_converted(
    session: AsyncSession, tree, approved, board
) -> None:
    ecr, _ = approved
    eco = await author_order(
        session,
        board,
        ecr.number,
        [
            ChangeOrderLineIn(
                action=ChangeAction.CHANGE_QUANTITY,
                parent_part_number="EC-MOD-200",
                child_part_number="EC-OLD-300",
                quantity=5,
            )
        ],
    )
    await release_change_order(
        session, actor=board[Role.SYSTEMS_ENGINEERING.value], number=eco.number
    )

    assert (await service.get_change_order(session, eco.number)).status is EcoStatus.RELEASED
    assert (
        await service.get_change_request(session, ecr.number)
    ).status is EcrStatus.CONVERTED


async def test_an_order_cannot_be_released_twice(
    session: AsyncSession, tree, approved, board
) -> None:
    ecr, _ = approved
    eco = await author_order(
        session,
        board,
        ecr.number,
        [
            ChangeOrderLineIn(
                action=ChangeAction.CHANGE_QUANTITY,
                parent_part_number="EC-MOD-200",
                child_part_number="EC-OLD-300",
                quantity=5,
            )
        ],
    )
    seat = board[Role.SYSTEMS_ENGINEERING.value]
    await release_change_order(session, actor=seat, number=eco.number)
    with pytest.raises(ToolError, match="cannot be released again"):
        await release_change_order(session, actor=seat, number=eco.number)


async def test_date_effectivity_hides_the_change_from_earlier_explodes(
    session: AsyncSession, tree, approved, board
) -> None:
    """An explode dated before the change returns the configuration of the day."""
    ecr, _ = approved
    future = datetime.now(timezone.utc).date() + timedelta(days=30)
    eco = await author_order(
        session,
        board,
        ecr.number,
        [
            ChangeOrderLineIn(
                action=ChangeAction.CHANGE_QUANTITY,
                parent_part_number="EC-MOD-200",
                child_part_number="EC-OLD-300",
                quantity=9,
            )
        ],
        effectivity_type=EffectivityType.DATE,
        effective_date=future,
    )
    await release_change_order(
        session, actor=board[Role.SYSTEMS_ENGINEERING.value], number=eco.number
    )

    today = flatten((await get_bom_structure(session, "EC-PRD-100")).tree)
    assert today["EC-MOD-200"].revision == "A"
    assert today["EC-OLD-300"].quantity == 4

    later = flatten(
        (
            await get_bom_structure(
                session, "EC-PRD-100", as_of=future + timedelta(days=1)
            )
        ).tree
    )
    assert later["EC-MOD-200"].revision == "B"
    assert later["EC-OLD-300"].quantity == 9


# --------------------------------------------------------------------------
# Through the agent write path
# --------------------------------------------------------------------------


async def test_releasing_through_a_tool_needs_systems_engineering_approval(
    session: AsyncSession, tree, approved, board, user_factory
) -> None:
    import uuid as _uuid

    from app.core.principal import agent_principal
    from app.core.proposals import ProposalError, ProposalStatus, decide
    from app.tools.registry import run_tool

    ecr, _ = approved
    eco = await author_order(
        session,
        board,
        ecr.number,
        [
            ChangeOrderLineIn(
                action=ChangeAction.CHANGE_QUANTITY,
                parent_part_number="EC-MOD-200",
                child_part_number="EC-OLD-300",
                quantity=5,
            )
        ],
    )

    result = await run_tool(
        session,
        "release_change_order",
        {"number": eco.number},
        actor=agent_principal("ECM Impact Analyst"),
    )
    assert result["status"] == "awaiting_approval"
    assert "EC-MOD-200 A to B" in result["summary"]

    # The preview ran the real release and rolled it back.
    assert (
        await service.get_change_order(session, eco.number)
    ).status is EcoStatus.DRAFT

    quality = principal_for(await user_factory(Role.QUALITY))
    with pytest.raises(ProposalError, match="systems_engineering"):
        await decide(
            session,
            proposal_id=_uuid.UUID(result["proposal_id"]),
            reviewer=quality,
            approve=True,
        )

    decided = await decide(
        session,
        proposal_id=_uuid.UUID(result["proposal_id"]),
        reviewer=board[Role.SYSTEMS_ENGINEERING.value],
        approve=True,
    )
    assert decided.status is ProposalStatus.APPLIED
    assert (
        await service.get_change_order(session, eco.number)
    ).status is EcoStatus.RELEASED

