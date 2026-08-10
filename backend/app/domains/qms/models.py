"""Quality management: units, as-built genealogy, test protocols, and NCRs.

The organising idea is that a **serial number is a thing, not a string**. Until
it is, "what is actually inside ECL-M-104?" has no answer better than "whatever
the drawing said at the time, probably". `Unit` gives the physical article an
identity, and `UnitComponent` records what went into that individual article —
including the lot each material came from, which is what a recall or a materials
investigation actually runs on.

`UnitComponent` is a **snapshot taken at build time**, not a view over the
current BOM. The BOM says what units of this type should contain now. The
genealogy says what this one did contain, then. Those diverge the moment an
engineering change is released, and the whole point of a build record is to
survive that divergence.

Pass/fail is likewise **stored, not recomputed**. A measurement was judged
against a specific revision of a specific protocol on the day it was taken, and
that judgement is the record. Recomputing it against today's limits would
silently rewrite history every time a specification is tightened.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import enum_values

if TYPE_CHECKING:
    from app.domains.pdm.models import Part


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class UnitStatus(str, enum.Enum):
    IN_PRODUCTION = "In production"
    IN_TEST = "In test"
    SHIPPED = "Shipped"
    IN_FIELD = "In field"
    RMA = "Returned"
    SCRAPPED = "Scrapped"


class TestResult(str, enum.Enum):
    PASS = "Pass"
    FAIL = "Fail"
    # No protocol was in force, so the reading is data but not a verdict.
    NOT_EVALUATED = "Not evaluated"


class NcrSource(str, enum.Enum):
    INCOMING_INSPECTION = "Incoming inspection"
    IN_PROCESS = "In process"
    FINAL_TEST = "Final test"
    FIELD = "Field"


class NcrSeverity(str, enum.Enum):
    MINOR = "Minor"
    MAJOR = "Major"
    CRITICAL = "Critical"


class NcrStatus(str, enum.Enum):
    OPEN = "Open"
    # The affected material has been quarantined; the disposition is still open.
    CONTAINED = "Contained"
    DISPOSITIONED = "Dispositioned"
    CLOSED = "Closed"


class Disposition(str, enum.Enum):
    PENDING = "Pending"
    USE_AS_IS = "Use as is"
    REWORK = "Rework"
    SCRAP = "Scrap"
    RETURN_TO_SUPPLIER = "Return to supplier"


class CapaKind(str, enum.Enum):
    # Stops this occurrence recurring.
    CORRECTIVE = "Corrective"
    # Stops the same class of problem arising elsewhere.
    PREVENTIVE = "Preventive"


# --------------------------------------------------------------------------
# Units and their as-built genealogy
# --------------------------------------------------------------------------


class Unit(Base):
    """One physical article, identified by its serial number."""

    __tablename__ = "units"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    serial_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    part_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="RESTRICT"), index=True
    )
    # The revision this individual was built to. Not the part's current
    # revision: that is the whole point.
    built_to_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("part_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The frozen configuration the build was taken from, where one was captured.
    as_built_baseline_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("configuration_baselines.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[UnitStatus] = mapped_column(
        SAEnum(
            UnitStatus,
            name="unit_status",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=UnitStatus.IN_PRODUCTION,
        index=True,
    )
    built_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    plant: Mapped[str | None] = mapped_column(String(64), nullable=True)
    customer_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    part: Mapped["Part"] = relationship("Part", foreign_keys=[part_id])
    components: Mapped[list["UnitComponent"]] = relationship(
        "UnitComponent",
        back_populates="unit",
        cascade="all, delete-orphan",
        order_by="UnitComponent.position",
    )
    test_records: Mapped[list["LabTestRecord"]] = relationship(
        "LabTestRecord",
        back_populates="unit",
        cascade="all, delete-orphan",
        order_by="LabTestRecord.recorded_at",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Unit {self.serial_number}>"


class UnitComponent(Base):
    """One line of a unit's build record: what went in, and where it came from.

    The lot number is the reason this table exists. Without it, a supplier
    problem found in one batch of material can only be answered with "every unit
    we have ever built, probably" — which is the same as no answer.
    """

    __tablename__ = "unit_components"
    __table_args__ = (
        Index("ix_unit_component_unit", "unit_id", "position"),
        # The backward trace — "which units contain this lot?" — runs on these.
        Index("ix_unit_component_lot", "lot_number"),
        Index("ix_unit_component_part", "part_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("units.id", ondelete="CASCADE")
    )
    part_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="RESTRICT")
    )
    part_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("part_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )

    quantity: Mapped[float] = mapped_column(Numeric(12, 4), default=1)
    unit_of_measure: Mapped[str] = mapped_column(String(16), default="ea")

    lot_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supplier_lot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # When the component is itself a serialised article, its serial. That is
    # what makes the genealogy a tree rather than a flat list.
    child_serial_number: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    # Path within the parent structure at build time, e.g. "100 / 110". Keeps
    # two occurrences of the same component distinguishable.
    position: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    unit: Mapped["Unit"] = relationship("Unit", back_populates="components")
    part: Mapped["Part"] = relationship("Part", foreign_keys=[part_id])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<UnitComponent {self.part_id} lot={self.lot_number}>"


# --------------------------------------------------------------------------
# Test protocols
# --------------------------------------------------------------------------


class TestProtocol(Base):
    """A named, revisioned set of acceptance limits.

    Revisioned because tightening a limit must not retroactively fail units
    that met the specification in force when they were tested.
    """

    __tablename__ = "test_protocols"
    __table_args__ = (UniqueConstraint("code", "revision", name="uq_protocol_revision"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code: Mapped[str] = mapped_column(String(32), index=True)
    revision: Mapped[str] = mapped_column(String(16), default="A")
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Which part this protocol accepts. Null means it applies generally.
    applies_to_part_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    limits: Mapped[list["TestSpecLimit"]] = relationship(
        "TestSpecLimit",
        back_populates="protocol",
        cascade="all, delete-orphan",
        order_by="TestSpecLimit.metric",
    )

    @property
    def label(self) -> str:
        return f"{self.code} rev {self.revision}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<TestProtocol {self.code} rev {self.revision}>"


class TestSpecLimit(Base):
    """One metric's acceptance band within a protocol.

    Both bounds are optional so a one-sided limit — "pressure drop no higher
    than 900 mbar", with no floor — is expressible without inventing a fake
    lower bound that a genuine reading could fall below.
    """

    __tablename__ = "test_spec_limits"
    __table_args__ = (UniqueConstraint("protocol_id", "metric", name="uq_spec_metric"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    protocol_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("test_protocols.id", ondelete="CASCADE")
    )
    metric: Mapped[str] = mapped_column(String(64))
    lower_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_limit: Mapped[float | None] = mapped_column(Float, nullable=True)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)

    protocol: Mapped["TestProtocol"] = relationship(
        "TestProtocol", back_populates="limits"
    )


class LabTestRecord(Base):
    """One time-series QMS sample, taken on a specific physical unit.

    Metric columns keep the engineering spec's casing — see
    `app/domains/qms/metrics.py`.
    """

    __tablename__ = "lab_test_records"
    __table_args__ = (
        # Every QMS query is "all samples for this unit, in time order".
        Index("ix_lab_unit_time", "unit_id", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("units.id", ondelete="CASCADE"), index=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # --- Time-series metrics ---------------------------------------------
    temperature_span_delta_K: Mapped[float] = mapped_column(Float)
    pressure_drop_mbar: Mapped[float] = mapped_column(Float)
    magnetization_cycles_hz: Mapped[float] = mapped_column(Float)
    cooling_capacity_W: Mapped[float] = mapped_column(Float)

    # --- Verdict -----------------------------------------------------------
    # The protocol revision this reading was judged against, and the judgement
    # itself. Both stored: see the module docstring.
    protocol_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_protocols.id", ondelete="SET NULL"),
        nullable=True,
    )
    result: Mapped[TestResult] = mapped_column(
        SAEnum(
            TestResult,
            name="test_result",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=TestResult.NOT_EVALUATED,
        index=True,
    )
    # Which metrics fell outside their band, with the values and the limits, so
    # a failure explains itself without being recomputed.
    breaches: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    # A result taken with an overdue/missing calibration remains evidence but
    # cannot be used as an acceptance verdict.
    is_valid: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    invalid_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    test_rig: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator: Mapped[str | None] = mapped_column(String(64), nullable=True)

    unit: Mapped["Unit"] = relationship("Unit", back_populates="test_records")
    protocol: Mapped["TestProtocol | None"] = relationship("TestProtocol")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<LabTestRecord {self.unit_id} @ {self.recorded_at}>"


# --------------------------------------------------------------------------
# Non-conformance and corrective action
# --------------------------------------------------------------------------


class NonConformance(Base):
    """Something is wrong with a unit, a part, or a lot of material.

    Scope is deliberately one of three things rather than always a unit. A
    supplier problem is a property of the *lot*, and forcing it to be recorded
    against one serial loses the fact that every other unit built from that lot
    is equally suspect.
    """

    __tablename__ = "non_conformances"
    __table_args__ = (Index("ix_ncr_status", "status", "raised_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text)

    source: Mapped[NcrSource] = mapped_column(
        SAEnum(
            NcrSource,
            name="ncr_source",
            native_enum=False,
            length=24,
            values_callable=enum_values,
        )
    )
    severity: Mapped[NcrSeverity] = mapped_column(
        SAEnum(
            NcrSeverity,
            name="ncr_severity",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=NcrSeverity.MINOR,
    )
    status: Mapped[NcrStatus] = mapped_column(
        SAEnum(
            NcrStatus,
            name="ncr_status",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=NcrStatus.OPEN,
    )

    # --- Scope: at least one of these ------------------------------------
    unit_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("units.id", ondelete="SET NULL"), nullable=True
    )
    part_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="SET NULL"), nullable=True
    )
    lot_number: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    disposition: Mapped[Disposition] = mapped_column(
        SAEnum(
            Disposition,
            name="ncr_disposition",
            native_enum=False,
            length=24,
            values_callable=enum_values,
        ),
        default=Disposition.PENDING,
    )
    disposition_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    raised_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    raised_by_label: Mapped[str] = mapped_column(String(128))
    raised_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Set when the non-conformance turns out to need a design change. This is
    # the join between finding a problem and fixing it properly; without it the
    # two processes run in separate systems and stop referring to each other.
    escalated_ecr_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )

    actions: Mapped[list["CapaAction"]] = relationship(
        "CapaAction",
        back_populates="non_conformance",
        cascade="all, delete-orphan",
        order_by="CapaAction.created_at",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<NonConformance {self.number}>"


class CapaAction(Base):
    """A corrective or preventive action taken against a non-conformance."""

    __tablename__ = "capa_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    non_conformance_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("non_conformances.id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[CapaKind] = mapped_column(
        SAEnum(
            CapaKind,
            name="capa_kind",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        )
    )
    description: Mapped[str] = mapped_column(Text)
    owner_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Recorded separately from completion: doing the action and confirming it
    # worked are different claims, and conflating them is how a CAPA gets
    # closed on the strength of having been attempted.
    effectiveness_check: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    non_conformance: Mapped["NonConformance"] = relationship(
        "NonConformance", back_populates="actions"
    )
