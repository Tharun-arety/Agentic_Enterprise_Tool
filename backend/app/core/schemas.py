"""Wire contracts for the cross-cutting infrastructure: audit and proposals."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.audit import AuditAction
from app.core.principal import ActorType
from app.core.proposals import ProposalStatus


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurred_at: datetime
    actor_type: ActorType
    actor_label: str
    action: AuditAction
    entity_type: str
    entity_id: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    reason: str | None = None
    correlation_id: uuid.UUID | None = None


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    proposed_by_agent: str
    tool_name: str
    arguments: dict[str, Any]
    summary: str
    preview: dict[str, Any]
    required_role: str
    status: ProposalStatus
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    applied_at: datetime | None = None
    result: dict[str, Any] | None = None


class ProposalDecision(BaseModel):
    """The reviewer's ruling on a pending proposal."""

    note: str | None = Field(
        default=None,
        max_length=2000,
        description="Why. Recorded on the proposal and in the audit trail.",
    )


class ProposalPreview(BaseModel):
    """What a mutating tool returns instead of performing its mutation.

    `summary` is the line the reviewer reads first and the agent repeats back to
    the user. `changes` is the structured diff the approval inbox renders — the
    UI must never have to parse the summary to find out what would happen.
    """

    summary: str
    entity_type: str
    entity_ref: str | None = None
    changes: list["ProposedChange"] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProposedChange(BaseModel):
    """One field- or row-level difference within a proposal."""

    kind: str  # "add" | "remove" | "modify"
    target: str  # what is changing, e.g. "BomEdge ECL-AMR-200 -> LFS-POR-010"
    field: str | None = None
    before: Any = None
    after: Any = None


ProposalPreview.model_rebuild()
