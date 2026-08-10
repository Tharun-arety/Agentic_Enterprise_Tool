"""ECM wire contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.ecm.models import (
    ChangeAction,
    ChangeOrigin,
    ChangePriority,
    EcoStatus,
    EcrStatus,
    EffectivityType,
    ReviewDecision,
)

# --------------------------------------------------------------------------
# Impact assessment
# --------------------------------------------------------------------------


class AffectedProduct(BaseModel):
    part_number: str
    description: str
    revision: str
    reached_via: list[str] = Field(default_factory=list)


class AffectedAssembly(BaseModel):
    part_number: str
    revision: str
    depth: int
    quantity: float


class AffectedDocument(BaseModel):
    document_number: str
    title: str
    kind: str
    latest_revision: str | None = None


class AffectedTestEvidence(BaseModel):
    """Test data recorded against a configuration the change would alter.

    Flagged because it is the requirement most often skipped: a change to a
    component invalidates the measurements taken on the assembly containing it
    until they are repeated.
    """

    serial_number: str
    part_number: str
    sample_count: int
    latest_recorded_at: datetime | None = None


class CostImpact(BaseModel):
    part_number: str
    baseline_from: str | None = None
    baseline_to: str | None = None
    before: float | None = None
    after: float | None = None
    delta: float | None = None
    note: str | None = None


class ImpactFindings(BaseModel):
    """Everything the change reaches. Computed, then frozen onto the request."""

    affected_items: list[str] = Field(default_factory=list)
    affected_assemblies: list[AffectedAssembly] = Field(default_factory=list)
    affected_products: list[AffectedProduct] = Field(default_factory=list)
    affected_documents: list[AffectedDocument] = Field(default_factory=list)
    revalidation_required: list[AffectedTestEvidence] = Field(default_factory=list)
    affected_baselines: list[str] = Field(default_factory=list)
    configuration_items: list[str] = Field(default_factory=list)
    cost_impact: list[CostImpact] = Field(default_factory=list)
    # Things the assessment could not determine, named rather than omitted.
    gaps: list[str] = Field(default_factory=list)


class ImpactAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    generated_at: datetime
    generated_by: str
    summary: str
    findings: ImpactFindings


# --------------------------------------------------------------------------
# Change request
# --------------------------------------------------------------------------


class ChangeBoardReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seat: str
    reviewer_label: str
    decision: ReviewDecision
    comment: str | None = None
    decided_at: datetime


class QuorumStatus(BaseModel):
    """Whether the board has said enough for a decision to carry."""

    required_seats: list[str]
    voted_seats: list[str]
    missing_seats: list[str]
    rejecting_seats: list[str] = Field(default_factory=list)
    blocking_seats: list[str] = Field(default_factory=list)
    satisfied: bool
    verdict: str  # "approved" | "rejected" | "blocked" | "incomplete"


class ChangeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    title: str
    problem_statement: str
    proposed_solution: str
    preliminary_impact: str | None = None
    originator_label: str
    origin: ChangeOrigin
    priority: ChangePriority
    status: EcrStatus
    created_at: datetime
    submitted_at: datetime | None = None
    decided_at: datetime | None = None

    affected_part_numbers: list[str] = Field(default_factory=list)
    reviews: list[ChangeBoardReviewOut] = Field(default_factory=list)
    quorum: QuorumStatus | None = None
    latest_assessment: ImpactAssessmentOut | None = None


class ChangeRequestCreate(BaseModel):
    title: str = Field(min_length=4, max_length=256)
    problem_statement: str = Field(min_length=10)
    proposed_solution: str = Field(min_length=10)
    affected_part_numbers: list[str] = Field(min_length=1)
    origin: ChangeOrigin = ChangeOrigin.RND
    priority: ChangePriority = ChangePriority.NORMAL
    preliminary_impact: str | None = None


class ReviewSubmission(BaseModel):
    decision: ReviewDecision
    comment: str | None = Field(default=None, max_length=2000)
    # Which seat the vote is cast as. Omitted, it is inferred when the reviewer
    # holds exactly one board seat.
    seat: str | None = None


# --------------------------------------------------------------------------
# Change order and notice
# --------------------------------------------------------------------------


class ChangeOrderLineIn(BaseModel):
    action: ChangeAction
    parent_part_number: str
    child_part_number: str | None = None
    new_child_part_number: str | None = None
    quantity: float | None = None
    find_number: str | None = None
    notes: str | None = None


class ChangeOrderLineOut(ChangeOrderLineIn):
    model_config = ConfigDict(from_attributes=True)

    sequence: int


class ChangeOrderCreate(BaseModel):
    change_request_number: str
    title: str = Field(min_length=4, max_length=256)
    disposition: str = Field(min_length=10)
    effectivity_type: EffectivityType = EffectivityType.ASAP
    effective_date: date | None = None
    effective_serial: str | None = None
    lines: list[ChangeOrderLineIn] = Field(min_length=1)


class ChangeNoticeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number: str
    body: str
    recipients: list[str]
    issued_at: datetime
    acknowledged_by: list[str] = Field(default_factory=list)


class ChangeOrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    title: str
    change_request_number: str
    disposition: str
    effectivity_type: EffectivityType
    effective_date: date | None = None
    effective_serial: str | None = None
    status: EcoStatus
    created_at: datetime
    released_at: datetime | None = None
    lines: list[ChangeOrderLineOut] = Field(default_factory=list)
    notices: list[ChangeNoticeOut] = Field(default_factory=list)


class RevisionCreated(BaseModel):
    part_number: str
    from_revision: str | None = None
    to_revision: str


class ReleaseResult(BaseModel):
    """What releasing a change order actually did."""

    change_order_number: str
    revisions_created: list[RevisionCreated] = Field(default_factory=list)
    edges_added: int = 0
    edges_removed: int = 0
    edges_modified: int = 0
    baselines_captured: list[str] = Field(default_factory=list)
    notice_number: str | None = None
    knowledge_indexed: bool = False
    warnings: list[str] = Field(default_factory=list)
