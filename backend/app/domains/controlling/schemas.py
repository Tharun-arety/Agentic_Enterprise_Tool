from __future__ import annotations
import uuid
from pydantic import BaseModel, Field
class MaterialLine(BaseModel):
    part_number: str; extended_quantity: float; standard_cost: float; extended_cost: float
class LabourLine(BaseModel):
    operation_seq: int; work_center: str; minutes_per_unit: float; hourly_rate: float; cost: float
class CostRollup(BaseModel):
    part_number: str; revision: str; batch_size: float; material_cost: float; labour_cost: float; total_cost: float; currency: str="EUR"; materials: list[MaterialLine]=Field(default_factory=list); labour: list[LabourLine]=Field(default_factory=list)
class VarianceRow(BaseModel):
    cost_centre: str; budget: float; commitments: float; actuals: float; variance: float; currency: str="EUR"
class SnapshotOut(BaseModel):
    id: uuid.UUID; total_cost: float; currency: str="EUR"
