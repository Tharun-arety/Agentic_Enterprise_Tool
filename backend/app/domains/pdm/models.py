"""Relational PDM schema: the part master, revisions, and the BOM graph.

Three structural decisions carry most of the weight here.

**Revisions are rows, not a string column.** "Which revision of the regenerator
was in unit ECL-M-104?" is unanswerable if a part carries one mutable
`revision` field. `PartRevision` owns the lifecycle state, the release
timestamp, and the change order that produced it.

**A BOM edge hangs off the parent's revision, not off the parent.** Changing
what an assembly contains *is* a change to that assembly, so its structure is
versioned with it. The child end points at the part rather than a specific
revision, and the effective child revision is resolved at query time — pinning
every child revision would make a leaf-level revision bump cascade edits all
the way up the tree for no engineering reason. `child_revision_id` exists for
the minority case where a design genuinely requires one exact revision.

**EBOM and MBOM are the same table under different `bom_type` values.** They
share a shape — a directed acyclic graph of quantities — and separating them
into two tables would mean two copies of the traversal, the effectivity logic,
and the cycle guard.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

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


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class MaterialType(str, enum.Enum):
    """Primary material class of a part.

    Modelled as an enum rather than free text so the BOM viewer can colour-code
    the magnetocaloric (LaFeSi) and magnet (Neodymium) components
    deterministically instead of string-matching a description field.
    """

    LAFESI = "LaFeSi"
    NEODYMIUM = "Neodymium"
    POLYMER = "Polymer"
    FLUID = "Fluid"
    COMPOSITE = "Composite"
    STEEL = "Steel"
    # Sub-assemblies and top-level systems are not made of one material.
    ASSEMBLY = "Assembly"


class CoatingStatus(str, enum.Enum):
    ANTI_CORROSION_METAL = "Anti-corrosion metal coating"
    EPOXY_BONDED = "Epoxy bonded"
    PASSIVATED = "Passivated"
    UNCOATED = "Uncoated"
    NOT_APPLICABLE = "N/A"


class PartClass(str, enum.Enum):
    """What kind of thing this is, for MBOM and procurement purposes.

    `PHANTOM` and `PACKAGING` exist because the MBOM needs them and the EBOM
    does not: a phantom is a kitting convenience with no engineering identity,
    and packaging is not part of the product's function.
    """

    MECHANICAL = "Mechanical"
    ELECTRICAL = "Electrical"
    ELECTROMECHANICAL = "Electromechanical"
    SOFTWARE = "Software"
    RAW_MATERIAL = "Raw material"
    CONSUMABLE = "Consumable"
    PACKAGING = "Packaging"
    PHANTOM = "Phantom"
    ASSEMBLY = "Assembly"
    DOCUMENT = "Document"


class LifecycleState(str, enum.Enum):
    """Where a *revision* sits in its life. Not a property of the part."""

    IN_DESIGN = "In design"
    IN_REVIEW = "In review"
    PROTOTYPE = "Prototype"
    RELEASED = "Released"
    OBSOLETE = "Obsolete"


class MakeOrBuy(str, enum.Enum):
    MAKE = "Make"
    BUY = "Buy"
    MAKE_OR_BUY = "Make or buy"


class BomType(str, enum.Enum):
    """Which view of the product structure an edge belongs to (DIN 199)."""

    EBOM = "EBOM"
    MBOM = "MBOM"


class CiCriticality(str, enum.Enum):
    """How closely a configuration item is controlled (ISO 10007 selection)."""

    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class Declaration(str, enum.Enum):
    """A compliance claim about a part.

    Tri-state on purpose. Rolling "PFAS-free" up a bill of materials that
    contains an unassessed component must produce "cannot prove", not "true" —
    a boolean would silently turn a gap in the data into a claim to a customer.
    """

    YES = "Yes"
    NO = "No"
    UNKNOWN = "Unknown"


class ComplianceStatus(str, enum.Enum):
    COMPLIANT = "Compliant"
    NON_COMPLIANT = "Non-compliant"
    EXEMPT = "Exempt"
    UNKNOWN = "Unknown"


class MbomDeltaType(str, enum.Enum):
    """How the manufacturing view departs from the engineering view."""

    ADD = "Add"
    REMOVE = "Remove"
    REQUANTIFY = "Requantify"
    PHANTOM = "Phantom"
    ROUTE = "Route"


class DocumentKind(str, enum.Enum):
    """A controlled file in the vault.

    Distinct from `app.domains.knowledge.models.DocumentType`, which classifies
    text in the retrieval corpus. This one classifies binaries under revision
    control.
    """

    CAD_MODEL = "CAD model"
    DRAWING = "Drawing"
    WORK_INSTRUCTION = "Work instruction"
    TEST_REPORT = "Test report"
    DATASHEET = "Datasheet"
    CERTIFICATE = "Certificate"
    SPECIFICATION = "Specification"


# --------------------------------------------------------------------------
# Part master
# --------------------------------------------------------------------------


class Part(Base):
    """A single item in the product data model — leaf part or assembly node.

    Holds only what is true of the item across every revision. Anything that
    changes when the design changes lives on `PartRevision`.
    """

    __tablename__ = "parts"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    part_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text)

    material_type: Mapped[MaterialType] = mapped_column(
        SAEnum(
            MaterialType,
            name="material_type",
            native_enum=False,
            length=32,
            values_callable=enum_values,
        )
    )
    coating_status: Mapped[CoatingStatus] = mapped_column(
        SAEnum(
            CoatingStatus,
            name="coating_status",
            native_enum=False,
            length=48,
            values_callable=enum_values,
        ),
        default=CoatingStatus.NOT_APPLICABLE,
    )
    part_class: Mapped[PartClass] = mapped_column(
        SAEnum(
            PartClass,
            name="part_class",
            native_enum=False,
            length=32,
            values_callable=enum_values,
        ),
        default=PartClass.MECHANICAL,
    )

    # --- Procurement and costing ------------------------------------------
    unit_of_measure: Mapped[str] = mapped_column(String(16), default="ea")
    make_or_buy: Mapped[MakeOrBuy] = mapped_column(
        SAEnum(
            MakeOrBuy,
            name="make_or_buy",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=MakeOrBuy.BUY,
    )
    # Numeric, not Float: money compared or summed in binary floating point
    # accumulates error that shows up as a cost rollup that does not tie out.
    standard_cost: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Configuration management (ISO 10007) -----------------------------
    is_configuration_item: Mapped[bool] = mapped_column(Boolean, default=False)
    ci_criticality: Mapped[CiCriticality | None] = mapped_column(
        SAEnum(
            CiCriticality,
            name="ci_criticality",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        nullable=True,
    )

    # --- Sustainability claims --------------------------------------------
    # The EBOM is the evidence base for "this product is PFAS-free and has zero
    # direct GWP", so the claim has to be attributable to individual components
    # rather than asserted at the top level.
    pfas_free: Mapped[Declaration] = mapped_column(
        SAEnum(
            Declaration,
            name="declaration",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=Declaration.UNKNOWN,
    )
    contains_heavy_rare_earth: Mapped[Declaration] = mapped_column(
        SAEnum(
            Declaration,
            name="declaration",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=Declaration.UNKNOWN,
    )
    rohs_reach_status: Mapped[ComplianceStatus] = mapped_column(
        SAEnum(
            ComplianceStatus,
            name="compliance_status",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=ComplianceStatus.UNKNOWN,
    )
    # kg CO2e per functional unit, direct only. Zero for a system with no
    # refrigerant gas, which is the point worth being able to prove.
    gwp_direct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Integration -------------------------------------------------------
    # Set once the part has been pushed to the back-office system, so the sync
    # can be idempotent rather than creating a duplicate item every run.
    external_ref: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    revisions: Mapped[list["PartRevision"]] = relationship(
        "PartRevision",
        back_populates="part",
        cascade="all, delete-orphan",
        foreign_keys="PartRevision.part_id",
        order_by="PartRevision.revision",
    )
    # Deliberately no `lab_tests` here. A measurement is taken on a physical
    # unit, not on a part number; reaching test data from a part now goes
    # through `Unit`, or through the as-built genealogy when the question is
    # "which units contain this component".

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Part {self.part_number}>"


class PartRevision(Base):
    """One issued revision of a part.

    A revision is the unit of release: it is what gets approved, what a BOM
    edge belongs to, and what an as-built record points at.
    """

    __tablename__ = "part_revisions"
    __table_args__ = (
        UniqueConstraint("part_id", "revision", name="uq_part_revision"),
        Index("ix_part_revision_state", "part_id", "lifecycle_state"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    part_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[str] = mapped_column(String(16))
    lifecycle_state: Mapped[LifecycleState] = mapped_column(
        SAEnum(
            LifecycleState,
            name="lifecycle_state",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        ),
        default=LifecycleState.IN_DESIGN,
    )

    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    released_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("part_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Which change order created this revision. Null for the initial issue and
    # for anything that predates the ECM process. No FK yet: the ECM tables
    # arrive in the next phase, and a forward reference would make this module
    # unimportable until then.
    created_by_eco_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    part: Mapped["Part"] = relationship(
        "Part", back_populates="revisions", foreign_keys=[part_id]
    )
    child_edges: Mapped[list["BomEdge"]] = relationship(
        "BomEdge",
        back_populates="parent_revision",
        cascade="all, delete-orphan",
        foreign_keys="BomEdge.parent_revision_id",
    )

    @property
    def is_released(self) -> bool:
        return self.lifecycle_state is LifecycleState.RELEASED

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PartRevision {self.part_id} rev {self.revision}>"


# --------------------------------------------------------------------------
# Product structure
# --------------------------------------------------------------------------


class BomEdge(Base):
    """A parent-revision -> child-part edge in a bill of materials.

    Structure lives in an edge table rather than a `parent_id` column on Part so
    that one part can appear in more than one assembly — the normal case for
    fasteners, seals, and shared sub-assemblies. A `parent_id` column would cap
    every part at exactly one parent and make the model wrong the first time a
    component is reused.
    """

    __tablename__ = "bom_edges"
    __table_args__ = (
        # A component may legitimately appear twice under one parent at
        # different find numbers (two of the same connector at different
        # positions), so the uniqueness key includes it.
        UniqueConstraint(
            "parent_revision_id",
            "child_part_id",
            "bom_type",
            "find_number",
            name="uq_bom_edge",
        ),
        Index("ix_bom_edge_parent", "parent_revision_id", "bom_type"),
        # Where-used runs this in reverse and is the hot path for change impact.
        Index("ix_bom_edge_child", "child_part_id", "bom_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    parent_revision_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("part_revisions.id", ondelete="CASCADE")
    )
    child_part_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="CASCADE")
    )
    # Pin the child to one exact revision. Normally null: the effective child
    # revision is resolved at query time to the latest released one, so a leaf
    # revision bump does not force an edit to every assembly above it.
    child_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("part_revisions.id", ondelete="SET NULL"),
        nullable=True,
    )

    bom_type: Mapped[BomType] = mapped_column(
        SAEnum(
            BomType,
            name="bom_type",
            native_enum=False,
            length=8,
            values_callable=enum_values,
        ),
        default=BomType.EBOM,
    )

    quantity: Mapped[float] = mapped_column(Numeric(12, 4), default=1)
    unit_of_measure: Mapped[str] = mapped_column(String(16), default="ea")
    # Position on the drawing / in the parts list. Called `find_number` rather
    # than `position` because that is what it is called on the drawing.
    find_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # ECAD reference designators for this line, e.g. "C12,C13".
    reference_designator: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # --- Effectivity -------------------------------------------------------
    # Phase-in and phase-out *within* a released revision. Both bounds are
    # half-open: effective_to is the first day the edge no longer applies.
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    # A serial break, for changes that take effect at a unit rather than a date.
    effective_from_serial: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Which change order opened and closed this line. Together these answer
    # "why is this component here?" without reading a document.
    eco_in_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    eco_out_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # --- MBOM-only ---------------------------------------------------------
    # Which routing step consumes this line on the shop floor.
    operation_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A kitting grouping with no engineering identity; exploded through rather
    # than stocked.
    is_phantom: Mapped[bool] = mapped_column(Boolean, default=False)
    # Expected loss, as a fraction: 0.02 means issue 2% more than the design
    # calls for.
    scrap_factor: Mapped[float] = mapped_column(Numeric(6, 4), default=0)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    parent_revision: Mapped["PartRevision"] = relationship(
        "PartRevision", back_populates="child_edges", foreign_keys=[parent_revision_id]
    )
    child_part: Mapped["Part"] = relationship("Part", foreign_keys=[child_part_id])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<BomEdge {self.bom_type.value} -> {self.child_part_id}>"


# --------------------------------------------------------------------------
# Manufacturing view
# --------------------------------------------------------------------------


class Operation(Base):
    """One routing step in the manufacturing process for a product revision."""

    __tablename__ = "operations"
    __table_args__ = (
        UniqueConstraint("root_revision_id", "op_seq", name="uq_operation_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    root_revision_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("part_revisions.id", ondelete="CASCADE"),
        index=True,
    )
    op_seq: Mapped[int] = mapped_column(Integer)
    work_center: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    setup_minutes: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    run_minutes: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    work_instruction_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Operation {self.op_seq} {self.work_center}>"


class MbomDelta(Base):
    """One documented departure of the manufacturing view from the design view.

    Stored as instructions rather than as a detached copy of the MBOM. Keeping
    the deltas means the EBOM-to-MBOM gap is inspectable — "what did
    manufacturing add, and why" is a query, not an archaeology exercise — and
    the MBOM can be rebuilt after the EBOM changes instead of being reconciled
    by hand.
    """

    __tablename__ = "mbom_deltas"
    __table_args__ = (Index("ix_mbom_delta_root", "root_revision_id", "sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    root_revision_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("part_revisions.id", ondelete="CASCADE")
    )
    # Order of application. Two deltas touching the same line must resolve
    # deterministically, or a rebuild produces a different MBOM each run.
    sequence: Mapped[int] = mapped_column(Integer, default=0)

    delta_type: Mapped[MbomDeltaType] = mapped_column(
        SAEnum(
            MbomDeltaType,
            name="mbom_delta_type",
            native_enum=False,
            length=16,
            values_callable=enum_values,
        )
    )
    # Where in the tree the change applies. Null means the root assembly.
    parent_part_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="CASCADE"), nullable=True
    )
    child_part_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="CASCADE"), nullable=True
    )

    quantity: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    unit_of_measure: Mapped[str | None] = mapped_column(String(16), nullable=True)
    operation_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_phantom: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    scrap_factor: Mapped[float | None] = mapped_column(Numeric(6, 4), nullable=True)

    # Why manufacturing needs this. Required, because an undocumented delta is
    # indistinguishable from a mistake the next time the MBOM is rebuilt.
    rationale: Mapped[str] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MbomDelta {self.delta_type.value} seq {self.sequence}>"


# --------------------------------------------------------------------------
# Configuration baselines
# --------------------------------------------------------------------------


class ConfigurationBaseline(Base):
    """A frozen snapshot of a product's structure at a point in time.

    The snapshot is stored as JSONB rather than recomputed from the live tables
    on demand. A baseline whose content changes when the underlying data changes
    is not a baseline — the entire purpose is to have something later states can
    be compared against and audited to.
    """

    __tablename__ = "configuration_baselines"
    __table_args__ = (UniqueConstraint("name", name="uq_baseline_name"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128))
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    root_part_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="CASCADE"), index=True
    )
    root_revision_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("part_revisions.id", ondelete="CASCADE")
    )
    bom_type: Mapped[BomType] = mapped_column(
        SAEnum(
            BomType,
            name="bom_type",
            native_enum=False,
            length=8,
            values_callable=enum_values,
        ),
        default=BomType.EBOM,
    )

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    captured_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    eco_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The flattened tree: one entry per line, each carrying its path so a part
    # appearing under two parents stays distinguishable.
    snapshot: Mapped[list[dict]] = mapped_column(JSONB)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ConfigurationBaseline {self.name}>"


# --------------------------------------------------------------------------
# Document vault
# --------------------------------------------------------------------------


class Document(Base):
    """A controlled file: CAD model, drawing, work instruction, certificate."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(256))
    kind: Mapped[DocumentKind] = mapped_column(
        SAEnum(
            DocumentKind,
            name="document_kind",
            native_enum=False,
            length=32,
            values_callable=enum_values,
        )
    )
    related_part_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parts.id", ondelete="SET NULL"), nullable=True
    )

    # Check-out. A held lock is what stops two engineers from each uploading a
    # revision derived from the same parent and one of them losing their work.
    locked_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    revisions: Mapped[list["DocumentRevision"]] = relationship(
        "DocumentRevision",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentRevision.uploaded_at",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Document {self.document_number}>"


class DocumentRevision(Base):
    """One uploaded version of a document's content."""

    __tablename__ = "document_revisions"
    __table_args__ = (
        UniqueConstraint("document_id", "revision", name="uq_document_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[str] = mapped_column(String(16))

    filename: Mapped[str] = mapped_column(String(256))
    content_type: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer)
    # SHA-256 of the bytes. Detects silent corruption in the object store and
    # makes "is this the file that was approved?" answerable.
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    # Opaque key into whichever FileStore implementation is configured.
    storage_key: Mapped[str] = mapped_column(String(512))

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    eco_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    document: Mapped["Document"] = relationship("Document", back_populates="revisions")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<DocumentRevision {self.document_id} rev {self.revision}>"
