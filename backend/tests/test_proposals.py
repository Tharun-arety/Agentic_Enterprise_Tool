"""The agent write path: preview, file, approve, apply.

Exercised through a throwaway tool registered for the duration of the test
rather than through a real domain tool. The contract under test belongs to the
registry and the proposal service, and binding these assertions to whichever
domain tool happens to mutate today would make them break for reasons that have
nothing to do with the spine.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditAction, AuditEvent
from app.core.principal import SYSTEM_PRINCIPAL, agent_principal
from app.core.proposals import (
    AgentProposal,
    ProposalError,
    ProposalStatus,
    decide,
)
from app.core.schemas import ProposalPreview, ProposedChange
from app.domains.identity.models import Role
from app.domains.pdm.models import CoatingStatus, MaterialType, Part
from app.tools.registry import TOOL_REGISTRY, ToolSpec, run_tool
from tests.conftest import principal_for

pytestmark = pytest.mark.db

TOOL_NAME = "test_rename_part"


async def _preview(session: AsyncSession, part_number: str, description: str):
    """Compute the change without making it."""
    part = (
        await session.execute(select(Part).where(Part.part_number == part_number))
    ).scalar_one()
    return ProposalPreview(
        summary=f"Reword the description of {part_number}",
        entity_type="Part",
        entity_ref=part_number,
        changes=[
            ProposedChange(
                kind="modify",
                target=f"Part {part_number}",
                field="description",
                before=part.description,
                after=description,
            )
        ],
    )


async def _apply(session: AsyncSession, *, actor, part_number: str, description: str):
    part = (
        await session.execute(select(Part).where(Part.part_number == part_number))
    ).scalar_one()
    part.description = description
    return {"part_number": part_number}


@pytest.fixture
def mutating_tool() -> Iterator[ToolSpec]:
    spec = ToolSpec(
        name=TOOL_NAME,
        domain="pdm",
        description="Test-only mutating tool.",
        parameters={"type": "object", "properties": {}},
        handler=_preview,
        applier=_apply,
        required_role=Role.SYSTEMS_ENGINEERING,
    )
    TOOL_REGISTRY[TOOL_NAME] = spec
    yield spec
    TOOL_REGISTRY.pop(TOOL_NAME, None)


@pytest.fixture
async def part(session: AsyncSession) -> Part:
    part = Part(
        part_number="TST-PRT-001",
        description="Original description",
        material_type=MaterialType.STEEL,
        coating_status=CoatingStatus.UNCOATED,
    )
    session.add(part)
    await session.commit()
    return part


def test_a_tool_with_an_applier_but_no_role_is_rejected() -> None:
    with pytest.raises(ValueError, match="required_role"):
        ToolSpec(
            name="unguarded",
            domain="pdm",
            description="",
            parameters={},
            handler=_preview,
            applier=_apply,
        )


async def test_read_tools_are_not_mutating() -> None:
    assert TOOL_REGISTRY["get_bom_structure"].mutates is False
    assert TOOL_REGISTRY["get_bom_structure"].applier is None


async def test_mutating_tool_files_a_proposal_instead_of_writing(
    session: AsyncSession, mutating_tool, part: Part
) -> None:
    result = await run_tool(
        session,
        TOOL_NAME,
        {"part_number": "TST-PRT-001", "description": "Reworded"},
        actor=agent_principal("PDM Agent"),
    )

    assert result["status"] == "awaiting_approval"
    assert result["required_role"] == Role.SYSTEMS_ENGINEERING.value

    await session.refresh(part)
    assert part.description == "Original description", "preview must not write"

    proposal = await session.get(AgentProposal, uuid.UUID(result["proposal_id"]))
    assert proposal is not None
    assert proposal.status is ProposalStatus.PENDING
    assert proposal.proposed_by_agent == "PDM Agent"
    assert proposal.preview["changes"][0]["after"] == "Reworded"


async def test_a_system_caller_cannot_trigger_a_mutation(
    session: AsyncSession, mutating_tool, part: Part
) -> None:
    # No named actor means no author for the resulting proposal, so the write
    # must be refused rather than attributed to nobody.
    result = await run_tool(
        session,
        TOOL_NAME,
        {"part_number": "TST-PRT-001", "description": "Reworded"},
        actor=SYSTEM_PRINCIPAL,
    )
    assert "error" in result
    assert await session.scalar(select(AgentProposal.id)) is None


async def test_approval_applies_the_change(
    session: AsyncSession, mutating_tool, part: Part, user_factory
) -> None:
    reviewer = await user_factory(Role.SYSTEMS_ENGINEERING)
    result = await run_tool(
        session,
        TOOL_NAME,
        {"part_number": "TST-PRT-001", "description": "Reworded"},
        actor=agent_principal("PDM Agent"),
    )
    proposal_id = uuid.UUID(result["proposal_id"])

    decided = await decide(
        session,
        proposal_id=proposal_id,
        reviewer=principal_for(reviewer),
        approve=True,
        note="Looks right.",
    )

    assert decided.status is ProposalStatus.APPLIED
    assert decided.applied_at is not None
    assert decided.reviewed_by == reviewer.id
    await session.refresh(part)
    assert part.description == "Reworded"


async def test_rejection_leaves_the_data_alone(
    session: AsyncSession, mutating_tool, part: Part, user_factory
) -> None:
    reviewer = await user_factory(Role.SYSTEMS_ENGINEERING)
    result = await run_tool(
        session,
        TOOL_NAME,
        {"part_number": "TST-PRT-001", "description": "Reworded"},
        actor=agent_principal("PDM Agent"),
    )

    decided = await decide(
        session,
        proposal_id=uuid.UUID(result["proposal_id"]),
        reviewer=principal_for(reviewer),
        approve=False,
        note="Wording is wrong.",
    )

    assert decided.status is ProposalStatus.REJECTED
    await session.refresh(part)
    assert part.description == "Original description"


async def test_reviewer_without_the_required_role_is_refused(
    session: AsyncSession, mutating_tool, part: Part, user_factory
) -> None:
    wrong_seat = await user_factory(Role.PROCUREMENT)
    result = await run_tool(
        session,
        TOOL_NAME,
        {"part_number": "TST-PRT-001", "description": "Reworded"},
        actor=agent_principal("PDM Agent"),
    )

    with pytest.raises(ProposalError, match="systems_engineering"):
        await decide(
            session,
            proposal_id=uuid.UUID(result["proposal_id"]),
            reviewer=principal_for(wrong_seat),
            approve=True,
        )
    await session.refresh(part)
    assert part.description == "Original description"


async def test_an_agent_cannot_approve_its_own_proposal(
    session: AsyncSession, mutating_tool, part: Part
) -> None:
    result = await run_tool(
        session,
        TOOL_NAME,
        {"part_number": "TST-PRT-001", "description": "Reworded"},
        actor=agent_principal("PDM Agent"),
    )
    with pytest.raises(ProposalError, match="signed-in person"):
        await decide(
            session,
            proposal_id=uuid.UUID(result["proposal_id"]),
            reviewer=agent_principal("PDM Agent"),
            approve=True,
        )


async def test_a_decided_proposal_cannot_be_decided_again(
    session: AsyncSession, mutating_tool, part: Part, user_factory
) -> None:
    reviewer = await user_factory(Role.SYSTEMS_ENGINEERING)
    result = await run_tool(
        session,
        TOOL_NAME,
        {"part_number": "TST-PRT-001", "description": "Reworded"},
        actor=agent_principal("PDM Agent"),
    )
    proposal_id = uuid.UUID(result["proposal_id"])
    await decide(
        session, proposal_id=proposal_id, reviewer=principal_for(reviewer), approve=True
    )

    with pytest.raises(ProposalError, match="already"):
        await decide(
            session,
            proposal_id=proposal_id,
            reviewer=principal_for(reviewer),
            approve=False,
        )


async def test_admin_can_approve_any_proposal(
    session: AsyncSession, mutating_tool, part: Part, user_factory
) -> None:
    admin = await user_factory(Role.ADMIN)
    result = await run_tool(
        session,
        TOOL_NAME,
        {"part_number": "TST-PRT-001", "description": "Reworded"},
        actor=agent_principal("PDM Agent"),
    )
    decided = await decide(
        session,
        proposal_id=uuid.UUID(result["proposal_id"]),
        reviewer=principal_for(admin),
        approve=True,
    )
    assert decided.status is ProposalStatus.APPLIED


async def test_the_whole_lifecycle_is_audited(
    session: AsyncSession, mutating_tool, part: Part, user_factory
) -> None:
    reviewer = await user_factory(Role.SYSTEMS_ENGINEERING)
    result = await run_tool(
        session,
        TOOL_NAME,
        {"part_number": "TST-PRT-001", "description": "Reworded"},
        actor=agent_principal("PDM Agent"),
    )
    await decide(
        session,
        proposal_id=uuid.UUID(result["proposal_id"]),
        reviewer=principal_for(reviewer),
        approve=True,
    )

    events = (
        await session.execute(
            select(AuditEvent)
            .where(AuditEvent.entity_type == "AgentProposal")
            .order_by(AuditEvent.occurred_at)
        )
    ).scalars().all()

    actions = [event.action for event in events]
    assert AuditAction.CREATE in actions, "the agent's proposal must be recorded"
    assert AuditAction.APPROVE in actions, "the human's approval must be recorded"

    created = next(e for e in events if e.action is AuditAction.CREATE)
    approved = next(e for e in events if e.action is AuditAction.APPROVE)
    assert created.actor_label == "agent:PDM Agent"
    assert approved.actor_label == reviewer.email
