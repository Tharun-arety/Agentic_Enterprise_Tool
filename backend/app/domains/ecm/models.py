"""Engineering change management: ECR, CCB review, ECO, ECN.

The four artefacts of a controlled change, in the order they occur:

1.  **ECR** — someone proposes a change and says why. Cheap to raise, and
    raising one is not a decision.
2.  **CCB review** — the cross-functional board rules on it. Each seat votes
    separately, because a change that helps one function routinely damages
    another and the point of the board is that nobody can wave that through
    alone.
3.  **ECO** — the authorisation to carry the change out, carrying the concrete
    line items and the effectivity that decides which units get it.
4.  **ECN** — the broadcast telling everyone, inside and out, that the
    configuration has moved.

Two modelling notes.

`ImpactAssessment` stores its findings as a snapshot rather than recomputing
them. The board votes on the assessment as it stood when it voted, and an
assessment that silently changes afterwards makes the vote unauditable.

`ChangeOrderLine` says what actually changes to the product structure. Without
it an ECO is prose, and releasing it means a human hand-editing the BOM and
hoping the edit matches the paperwork.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import enum_values


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class ChangeOrigin(str, enum.Enum):
    """Where the pressure for the change came from.

    Worth recording because the mix is diagnostic: a quarter of changes
    originating in `SUPPLY_CHAIN` says something different about a programme
    than a quarter originating in `FIELD`.
    """

    RND = "R&D"
    SUPPLY_CHAIN = "Supply chain"
    QUALITY = "Quality"
    FIELD = "Field"
    COST = "Cost reduction"
    REGULATORY = "Regulatory"


class ChangePriority(str, enum.Enum):
    LOW = "Low"
    NORMAL = "Normal"
    HIGH = "High"
    URGENT = "Urgent"


class EcrStatus(str, enum.Enum):
    DRAFT = "Draft"
    SUBMITTED = "Submitted"
    UNDER_REVIEW = "Under review"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    CONVERTED = "Converted"
    CANCELLED = "Cancelled"


class EcoStatus(str, enum.Enum):
    DRAFT = "Draft"
    RELEASED = "Released"
    CANCELLED = "Cancelled"


class ReviewDecision(str, enum.Enum):
    APPROVE = "Approve"
    REJECT = "Reject"
    # Present, deliberately not blocking: a seat with no stake should be able to
    # say so without either holding the change up or endorsing it.
    ABSTAIN = "Abstain"
    # Blocking, but not a rejection: the board cannot rule on what it has not
    # been told.
    REQUEST_INFO = "Request info"


class EffectivityType(str, enum.Enum):
    """When the change takes hold."""

    ASAP = "As soon as possible"
    DATE = "On a date"
    SERIAL = "From a serial number"


class ChangeAction(str, enum.Enum):
    """What one line of a change order does to the product structure."""

    ADD_COMPONENT = "Add component"
    REMOVE_COMPONENT = "Remove component"
    CHANGE_QUANTITY = "Change quantity"
    REPLACE_COMPONENT = "Replace component"
    # No structural change: the part's own attributes move, which still earns a
    # new revision because the released record has changed.
    REVISE_ATTRIBUTES = "Revise attributes"


# --------------------------------------------------------------------------
# Engineering Change Request
# --------------------------------------------------------------------------


class ChangeRequest(Base):
    __tablename__ = "change_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))

    problem_statement: Mapped[str] = mapped_column(Text)
    proposed_solution: Mapped[str] = mapped_column(Text)
    preliminary_impact: Mapped[str | None] = mapped_column(Text, nullable=True)

    originator_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    originator_label: Mapped[str] = mapped_column(String(128))
    origin: Mapped[ChangeOrigin] = mapped_column(
        SAEnum(
            ChangeOrigin,
            name="change_origin",
            native_enum=False,
            length=24,
            values_callable=enum_values,
        )
    )
    priority: Mapped[ChangePriority] = mapped_column(
        SAEnum(
            ChangePriority,
            name="change_priority",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=ChangePriority.NORMAL,
    )
    status: Mapped[EcrStatus] = mapped_column(
        SAEnum(
            EcrStatus,
            name="ecr_status",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=EcrStatus.DRAFT,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    affected_items: Mapped[list["ChangeAffectedItem"]] = relationship(
        "ChangeAffectedItem",
        back_populates="change_request",
        cascade="all, delete-orphan",
    )
    reviews: Mapped[list["ChangeBoardReview"]] = relationship(
        "ChangeBoardReview",
        back_populates="change_request",
        cascade="all, delete-orphan",
        order_by="ChangeBoardReview.decided_at",
    )
    assessments: Mapped[list["ImpactAssessment"]] = relationship(
        "ImpactAssessment",
        back_populates="change_request",
        cascade="all, delete-orphan",
        order_by="ImpactAssessment.generated_at",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ChangeRequest {self.number}>"


class ChangeAffectedItem(Base):
    """A configuration item the request proposes to touch."""

    __tablename__ = "change_affected_items"
    __table_args__ = (
        UniqueConstraint("change_request_id", "part_id", name="uq_affected_item"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    change_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("change_requests.id", ondelete="CASCADE")
    )
    part_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="CASCADE")
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    change_request: Mapped["ChangeRequest"] = relationship(
        "ChangeRequest", back_populates="affected_items"
    )


class ImpactAssessment(Base):
    """What the change would reach, computed rather than typed."""

    __tablename__ = "impact_assessments"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    change_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_requests.id", ondelete="CASCADE"),
        index=True,
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    generated_by: Mapped[str] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(Text)
    # The full structured finding, frozen. See the module docstring.
    findings: Mapped[dict] = mapped_column(JSONB)

    change_request: Mapped["ChangeRequest"] = relationship(
        "ChangeRequest", back_populates="assessments"
    )


class ChangeBoardReview(Base):
    """One Change Control Board seat's ruling on a request."""

    __tablename__ = "change_board_reviews"
    __table_args__ = (
        # One vote per seat. A member holding two seats votes once for each,
        # and cannot vote twice for the same one.
        UniqueConstraint("change_request_id", "seat", name="uq_ccb_seat_vote"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    change_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("change_requests.id", ondelete="CASCADE"),
        index=True,
    )
    # The role the vote is cast as, not merely the voter's identity: the board's
    # composition is what makes a quorum meaningful.
    seat: Mapped[str] = mapped_column(String(32))
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    reviewer_label: Mapped[str] = mapped_column(String(128))
    decision: Mapped[ReviewDecision] = mapped_column(
        SAEnum(
            ReviewDecision,
            name="review_decision",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        )
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    change_request: Mapped["ChangeRequest"] = relationship(
        "ChangeRequest", back_populates="reviews"
    )


# --------------------------------------------------------------------------
# Engineering Change Order
# --------------------------------------------------------------------------


class ChangeOrder(Base):
    __tablename__ = "change_orders"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    change_request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("change_requests.id", ondelete="RESTRICT")
    )
    disposition: Mapped[str] = mapped_column(Text)

    effectivity_type: Mapped[EffectivityType] = mapped_column(
        SAEnum(
            EffectivityType,
            name="effectivity_type",
            native_enum=False,
            length=32,
            values_callable=enum_values,
        ),
        default=EffectivityType.ASAP,
    )
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_serial: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[EcoStatus] = mapped_column(
        SAEnum(
            EcoStatus,
            name="eco_status",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=EcoStatus.DRAFT,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    released_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )

    lines: Mapped[list["ChangeOrderLine"]] = relationship(
        "ChangeOrderLine",
        back_populates="change_order",
        cascade="all, delete-orphan",
        order_by="ChangeOrderLine.sequence",
    )
    notices: Mapped[list["ChangeNotice"]] = relationship(
        "ChangeNotice", back_populates="change_order", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ChangeOrder {self.number}>"


class ChangeOrderLine(Base):
    """One concrete edit the change order makes to the product structure."""

    __tablename__ = "change_order_lines"
    __table_args__ = (Index("ix_eco_line_order", "change_order_id", "sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    change_order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("change_orders.id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    action: Mapped[ChangeAction] = mapped_column(
        SAEnum(
            ChangeAction,
            name="change_action",
            native_enum=False,
            length=24,
            values_callable=enum_values,
        )
    )

    # The assembly being modified. Its revision is what gets bumped.
    parent_part_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="CASCADE")
    )
    child_part_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="CASCADE"), nullable=True
    )
    # For REPLACE_COMPONENT: what goes in.
    new_child_part_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="CASCADE"), nullable=True
    )

    quantity: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    find_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    change_order: Mapped["ChangeOrder"] = relationship(
        "ChangeOrder", back_populates="lines"
    )


# --------------------------------------------------------------------------
# Engineering Change Notice
# --------------------------------------------------------------------------


class ChangeNotice(Base):
    """The broadcast that a released change has moved the configuration."""

    __tablename__ = "change_notices"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    change_order_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("change_orders.id", ondelete="CASCADE")
    )
    body: Mapped[str] = mapped_column(Text)
    # Internal roles and named external partners alike — a contract manufacturer
    # building to the old configuration needs telling as much as the shop floor.
    recipients: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    issued_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )

    change_order: Mapped["ChangeOrder"] = relationship(
        "ChangeOrder", back_populates="notices"
    )
    acknowledgements: Mapped[list["ChangeNoticeAcknowledgement"]] = relationship(
        "ChangeNoticeAcknowledgement",
        back_populates="notice",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ChangeNotice {self.number}>"


class ChangeNoticeAcknowledgement(Base):
    """Confirmation that a recipient has seen the notice.

    Issuing a notice is not the same as it having landed. Without this the
    question "does the contract manufacturer know?" has no answer.
    """

    __tablename__ = "change_notice_acknowledgements"
    __table_args__ = (
        UniqueConstraint("notice_id", "recipient", name="uq_notice_ack"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    notice_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("change_notices.id", ondelete="CASCADE")
    )
    recipient: Mapped[str] = mapped_column(String(64))
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )

    notice: Mapped["ChangeNotice"] = relationship(
        "ChangeNotice", back_populates="acknowledgements"
    )
