"""PDM wire contracts.

`frontend/lib/types.ts` mirrors these by hand; if you change a shape here,
change it there too.

Quantities cross the wire as floats although the columns are `Numeric`. The
precision matters where values are summed — cost rollups — and that arithmetic
happens in Postgres or in `Decimal` on the server. What the browser receives is
for display.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.pdm.models import (
    BomType,
    CiCriticality,
    CoatingStatus,
    ComplianceStatus,
    Declaration,
    DocumentKind,
    LifecycleState,
    MakeOrBuy,
    MaterialType,
    MbomDeltaType,
    PartClass,
)

# --------------------------------------------------------------------------
# Part master
# --------------------------------------------------------------------------


class PartRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    revision: str
    lifecycle_state: LifecycleState
    released_at: datetime | None = None
    change_summary: str | None = None
    created_by_eco_id: uuid.UUID | None = None
    created_at: datetime


class PartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    part_number: str
    description: str
    material_type: MaterialType
    coating_status: CoatingStatus
    part_class: PartClass
    unit_of_measure: str
    make_or_buy: MakeOrBuy
    standard_cost: float | None = None
    currency: str
    lead_time_days: int | None = None
    is_configuration_item: bool
    ci_criticality: CiCriticality | None = None
    pfas_free: Declaration
    contains_heavy_rare_earth: Declaration
    rohs_reach_status: ComplianceStatus
    gwp_direct: float | None = None


class PartDetail(PartOut):
    """A part with its full revision history."""

    revisions: list[PartRevisionOut] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Bill of materials
# --------------------------------------------------------------------------


class BomNode(BaseModel):
    """One node of a bill-of-materials tree, including its children."""

    model_config = ConfigDict(from_attributes=True)

    part_number: str
    description: str
    material_type: MaterialType
    coating_status: CoatingStatus
    part_class: PartClass
    revision: str
    lifecycle_state: LifecycleState

    quantity: float = 1
    # Quantity of this component per one of the *root* item, with scrap
    # compounded down the tree. What procurement actually needs.
    extended_quantity: float = 1
    unit_of_measure: str = "ea"

    find_number: str | None = None
    reference_designator: str | None = None

    # MBOM-only; null or default on an EBOM line.
    operation_seq: int | None = None
    is_phantom: bool = False
    scrap_factor: float = 0

    is_configuration_item: bool = False
    pfas_free: Declaration = Declaration.UNKNOWN
    contains_heavy_rare_earth: Declaration = Declaration.UNKNOWN
    rohs_reach_status: ComplianceStatus = ComplianceStatus.UNKNOWN
    gwp_direct: float | None = None
    standard_cost: float | None = None

    depth: int = 0
    children: list["BomNode"] = Field(default_factory=list)


BomNode.model_rebuild()


class BomResponse(BaseModel):
    root_part_number: str
    root_revision: str
    bom_type: BomType
    as_of: date
    total_nodes: int
    max_depth: int
    tree: BomNode


# --------------------------------------------------------------------------
# Where-used
# --------------------------------------------------------------------------


class WhereUsedRow(BaseModel):
    part_number: str
    description: str
    part_class: PartClass
    revision: str
    lifecycle_state: LifecycleState
    is_configuration_item: bool
    quantity: float
    depth: int
    # The component one level down through which this assembly reaches the
    # target — the path, one hop at a time.
    via_part_number: str
    # Nothing contains this one, so it is a shippable product. The set an
    # engineering change notice has to name.
    is_top_level: bool


class WhereUsedResponse(BaseModel):
    part_number: str
    bom_type: BomType
    as_of: date
    total_parents: int
    top_level_products: list[str] = Field(default_factory=list)
    rows: list[WhereUsedRow] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Compliance
# --------------------------------------------------------------------------


class ComplianceGap(BaseModel):
    part_number: str
    description: str
    attribute: str
    value: str


class ComplianceRollup(BaseModel):
    """Whether a product's sustainability claims are provable from its BOM.

    Three outcomes, not two. `proven` means every component declares the claim.
    `violated` means at least one component contradicts it. `unproven` means
    nothing contradicts it but some components have never been assessed — which
    is not the same as compliant, and must not be reported as though it were.
    """

    root_part_number: str
    bom_type: BomType
    as_of: date
    components_assessed: int

    pfas_free: str
    heavy_rare_earth_free: str
    rohs_reach: str
    total_direct_gwp: float | None = None

    gaps: list[ComplianceGap] = Field(default_factory=list)
    violations: list[ComplianceGap] = Field(default_factory=list)


# --------------------------------------------------------------------------
# MBOM derivation
# --------------------------------------------------------------------------


class MbomDeltaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence: int
    delta_type: MbomDeltaType
    parent_part_number: str | None = None
    child_part_number: str | None = None
    quantity: float | None = None
    unit_of_measure: str | None = None
    operation_seq: int | None = None
    is_phantom: bool | None = None
    scrap_factor: float | None = None
    rationale: str


class OperationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    op_seq: int
    work_center: str
    description: str
    setup_minutes: float
    run_minutes: float


class MbomDerivationResult(BaseModel):
    """What `derive_mbom` did, in terms a production planner can check."""

    root_part_number: str
    root_revision: str
    edges_copied_from_ebom: int
    deltas_applied: int
    edges_after: int
    deltas: list[MbomDeltaOut] = Field(default_factory=list)
    operations: list[OperationOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------


class BaselineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    platform: str | None = None
    bom_type: BomType
    captured_at: datetime
    eco_id: uuid.UUID | None = None
    notes: str | None = None
    line_count: int


class BaselineDiffRow(BaseModel):
    kind: str  # "added" | "removed" | "changed"
    path: str
    part_number: str
    field: str | None = None
    before: str | None = None
    after: str | None = None


class BaselineDiff(BaseModel):
    from_baseline: str
    to_baseline: str
    added: list[BaselineDiffRow] = Field(default_factory=list)
    removed: list[BaselineDiffRow] = Field(default_factory=list)
    changed: list[BaselineDiffRow] = Field(default_factory=list)
    unchanged_count: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------


class DocumentRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    revision: str
    filename: str
    content_type: str
    size_bytes: int
    content_hash: str
    uploaded_at: datetime
    notes: str | None = None


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_number: str
    title: str
    kind: DocumentKind
    related_part_number: str | None = None
    locked_by: uuid.UUID | None = None
    locked_at: datetime | None = None
    revisions: list[DocumentRevisionOut] = Field(default_factory=list)
