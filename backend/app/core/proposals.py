"""The agent write path: agents propose, humans dispose.

A read tool answers a question and the worst case is a wrong answer. A write
tool changes the product record, and the worst case is a change nobody
authorised sitting in the configuration baseline. So mutating tools do not
execute when an agent calls them. They run a **preview**, which computes exactly
what would change without writing anything, and file an `AgentProposal`. A human
holding the right role approves it, and only then does the applier run.

That gives three properties worth the indirection:

*   Nothing an agent does takes effect on its own authority.
*   The reviewer sees the concrete diff, not the model's description of it.
*   Approval is an attributable act, recorded against a named person — which is
    what an engineering change sign-off has to be to mean anything.
"""

from __future__ import annotations

import enum
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Enum as SAEnum, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core import audit
from app.core.audit import AuditAction
from app.core.db import Base
from app.core.enums import enum_values
from app.core.principal import ActorType, Principal
from app.domains.identity.models import Role

logger = logging.getLogger(__name__)


class ProposalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    FAILED = "failed"


class ProposalError(Exception):
    """The proposal cannot be acted on as requested."""


class AgentProposal(Base):
    """A mutation an agent has prepared and a human has not yet ruled on."""

    __tablename__ = "agent_proposals"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    proposed_by_agent: Mapped[str] = mapped_column(String(64))
    tool_name: Mapped[str] = mapped_column(String(64), index=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)

    # What the reviewer is shown: a one-line summary plus the structured diff
    # the preview computed. Stored rather than recomputed on open, so the
    # reviewer approves the change they were shown even if the underlying data
    # has moved since.
    summary: Mapped[str] = mapped_column(Text)
    preview: Mapped[dict[str, Any]] = mapped_column(JSONB)

    # The role a reviewer must hold to approve this specific proposal. Set from
    # the tool's declaration, so authority lives with the operation rather than
    # in a rule the endpoint has to remember to apply.
    required_role: Mapped[str] = mapped_column(String(32))

    status: Mapped[ProposalStatus] = mapped_column(
        SAEnum(
            ProposalStatus,
            name="proposal_status",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=ProposalStatus.PENDING,
        index=True,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Ties the proposal back to the agent turn that produced it.
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AgentProposal {self.tool_name} {self.status.value}>"


async def file_proposal(
    session: AsyncSession,
    *,
    actor: Principal,
    tool_name: str,
    arguments: dict[str, Any],
    summary: str,
    preview: dict[str, Any],
    required_role: Role,
    correlation_id: uuid.UUID | None = None,
) -> AgentProposal:
    """Record a prepared mutation awaiting human approval."""
    proposal = AgentProposal(
        proposed_by_agent=actor.agent_name or actor.label,
        tool_name=tool_name,
        arguments=arguments,
        summary=summary,
        preview=preview,
        required_role=required_role.value,
        status=ProposalStatus.PENDING,
        correlation_id=correlation_id,
    )
    session.add(proposal)
    await session.flush()  # assign the id the caller reports back to the user

    audit.record(
        session,
        actor=actor,
        action=AuditAction.CREATE,
        entity_type="AgentProposal",
        entity_id=proposal.id,
        after={"tool": tool_name, "arguments": arguments, "summary": summary},
        correlation_id=correlation_id,
    )
    await session.commit()
    logger.info(
        "Proposal %s filed by %s for %s", proposal.id, actor.label, tool_name
    )
    return proposal


async def decide(
    session: AsyncSession,
    *,
    proposal_id: uuid.UUID,
    reviewer: Principal,
    approve: bool,
    note: str | None = None,
) -> AgentProposal:
    """Approve or reject a pending proposal, applying it on approval.

    The whole decision — status change, applier execution, audit events — is one
    transaction. A proposal marked applied whose applier half-ran is the one
    outcome this must not produce.
    """
    proposal = await session.get(AgentProposal, proposal_id)
    if proposal is None:
        raise ProposalError(f"No proposal {proposal_id}.")
    if proposal.status is not ProposalStatus.PENDING:
        raise ProposalError(
            f"Proposal {proposal_id} is already {proposal.status.value}; "
            "a decision cannot be revisited."
        )

    if reviewer.actor_type is not ActorType.HUMAN:
        raise ProposalError(
            "Only a signed-in person can decide a proposal. An agent approving "
            "its own work would make the approval step decorative."
        )

    required = Role(proposal.required_role)
    if not reviewer.has_role(required):
        raise ProposalError(
            f"Approving this requires the {required.value!r} role. "
            f"{reviewer.label} holds {', '.join(reviewer.roles) or 'no roles'}."
        )

    now = datetime.now(timezone.utc)
    proposal.reviewed_by = reviewer.user_id
    proposal.reviewed_at = now
    proposal.review_note = note

    if not approve:
        proposal.status = ProposalStatus.REJECTED
        audit.record(
            session,
            actor=reviewer,
            action=AuditAction.REJECT,
            entity_type="AgentProposal",
            entity_id=proposal.id,
            before={"status": ProposalStatus.PENDING.value},
            after={"status": ProposalStatus.REJECTED.value},
            reason=note,
            correlation_id=proposal.correlation_id,
        )
        await session.commit()
        return proposal

    # Imported here rather than at module scope: the registry imports domain
    # tool modules, and those import this module to declare their appliers.
    from app.tools.registry import TOOL_REGISTRY

    spec = TOOL_REGISTRY.get(proposal.tool_name)
    if spec is None or spec.applier is None:
        raise ProposalError(
            f"Tool {proposal.tool_name!r} has no applier registered; the "
            "proposal cannot be carried out."
        )

    proposal.status = ProposalStatus.APPROVED
    audit.record(
        session,
        actor=reviewer,
        action=AuditAction.APPROVE,
        entity_type="AgentProposal",
        entity_id=proposal.id,
        before={"status": ProposalStatus.PENDING.value},
        after={"status": ProposalStatus.APPROVED.value},
        reason=note,
        correlation_id=proposal.correlation_id,
    )

    try:
        result = await spec.applier(
            session, actor=reviewer, **proposal.arguments
        )
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
        await session.rollback()
        # A fresh transaction: the failure record must survive the rollback
        # that undid the partial write.
        failed = await session.get(AgentProposal, proposal_id)
        if failed is not None:
            failed.status = ProposalStatus.FAILED
            failed.reviewed_by = reviewer.user_id
            failed.reviewed_at = now
            failed.result = {"error": f"{type(exc).__name__}: {exc}"}
            await session.commit()
        logger.exception("Applying proposal %s failed", proposal_id)
        raise ProposalError(f"Applying the change failed: {exc}") from exc

    proposal.status = ProposalStatus.APPLIED
    proposal.applied_at = datetime.now(timezone.utc)
    proposal.result = result if isinstance(result, dict) else {"result": str(result)}
    await session.commit()
    logger.info("Proposal %s applied by %s", proposal_id, reviewer.label)
    return proposal
