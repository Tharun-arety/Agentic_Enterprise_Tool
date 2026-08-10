"""QMS wire contracts.

Metric field names keep the engineering spec's casing all the way from the ORM
column to the React chart — see `app/domains/qms/metrics.py`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domains.qms.models import (
    CapaKind,
    Disposition,
    NcrSeverity,
    NcrSource,
    NcrStatus,
    TestResult,
    UnitStatus,
)

# --------------------------------------------------------------------------
# Test records and metrics
# --------------------------------------------------------------------------


class MetricBreach(BaseModel):
    """One metric outside its acceptance band, with the band that was applied."""

    metric: str
    unit: str
    value: float
    lower_limit: float | None = None
    upper_limit: float | None = None


class LabTestRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    recorded_at: datetime
    temperature_span_delta_K: float
    pressure_drop_mbar: float
    magnetization_cycles_hz: float
    cooling_capacity_W: float
    result: TestResult
    breaches: list[MetricBreach] = Field(default_factory=list)
    test_rig: str | None = None
    operator: str | None = None


class MetricSummary(BaseModel):
    """Min/max/mean/latest for one metric across the returned window."""

    metric: str
    unit: str
    minimum: float
    maximum: float
    mean: float
    latest: float
    lower_limit: float | None = None
    upper_limit: float | None = None


class QmsResponse(BaseModel):
    serial_number: str
    part_number: str | None = None
    built_to_revision: str | None = None
    status: UnitStatus | None = None
    protocol: str | None = None
    sample_count: int
    pass_count: int = 0
    fail_count: int = 0
    records: list[LabTestRecordOut]
    summaries: list[MetricSummary]


# --------------------------------------------------------------------------
# Units and genealogy
# --------------------------------------------------------------------------


class GenealogyLine(BaseModel):
    part_number: str
    description: str
    revision: str | None = None
    quantity: float
    unit_of_measure: str
    lot_number: str | None = None
    supplier_lot: str | None = None
    child_serial_number: str | None = None
    position: str | None = None
    operation_seq: int | None = None
    installed_at: datetime | None = None
    depth: int
    parent_serial: str


class UnitGenealogy(BaseModel):
    """A unit's build record: what this individual article actually contains."""

    serial_number: str
    part_number: str
    built_to_revision: str | None = None
    status: UnitStatus
    built_at: datetime | None = None
    plant: str | None = None
    customer_ref: str | None = None
    as_built_baseline: str | None = None
    line_count: int
    lots: list[str] = Field(default_factory=list)
    lines: list[GenealogyLine] = Field(default_factory=list)


class TracedUnit(BaseModel):
    serial_number: str
    part_number: str
    status: str
    built_at: datetime | None = None
    customer_ref: str | None = None
    # 0 when the unit contains the lot directly, higher when it is reached
    # through a serialised sub-assembly.
    depth: int


class LotTrace(BaseModel):
    lot_number: str
    unit_count: int
    units: list[TracedUnit] = Field(default_factory=list)


class BuildResult(BaseModel):
    serial_number: str
    part_number: str
    built_to_revision: str
    bom_type_used: str
    components_recorded: int
    lots_assigned: int
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Non-conformance
# --------------------------------------------------------------------------


class CapaActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: CapaKind
    description: str
    owner_label: str | None = None
    due_date: date | None = None
    completed_at: datetime | None = None
    effectiveness_check: str | None = None


class NonConformanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    number: str
    title: str
    description: str
    source: NcrSource
    severity: NcrSeverity
    status: NcrStatus
    disposition: Disposition
    disposition_note: str | None = None
    serial_number: str | None = None
    part_number: str | None = None
    lot_number: str | None = None
    raised_by_label: str
    raised_at: datetime
    closed_at: datetime | None = None
    escalated_ecr_number: str | None = None
    # Filled for a lot-scoped NCR: every unit the bad material reached.
    affected_units: list[str] = Field(default_factory=list)
    actions: list[CapaActionOut] = Field(default_factory=list)


class NonConformanceCreate(BaseModel):
    title: str = Field(min_length=4, max_length=256)
    description: str = Field(min_length=10)
    source: NcrSource
    severity: NcrSeverity = NcrSeverity.MINOR
    serial_number: str | None = None
    part_number: str | None = None
    lot_number: str | None = None


class DispositionRequest(BaseModel):
    disposition: Disposition
    note: str | None = Field(default=None, max_length=2000)
