from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.domains.controlling.models import Actual, Budget, Commitment, CostCentre, CostRollupSnapshot, WorkCentreRate
from app.domains.controlling.schemas import CostRollup, LabourLine, MaterialLine, VarianceRow
from app.domains.pdm.models import Operation, Part, PartClass, PartRevision
from app.domains.pdm.service import get_bom_structure
from app.tools.registry import ToolError

Q=Decimal("0.0001")
def money(value: Decimal) -> float: return float(value.quantize(Q,rounding=ROUND_HALF_UP))

async def rollup_cost(session: AsyncSession, part_number: str, batch_size: float=1) -> CostRollup:
    if batch_size <= 0: raise ToolError("Batch size must be greater than zero.")
    bom=await get_bom_structure(session,part_number,bom_type="MBOM")
    material_lines=[]; material_total=Decimal(0)
    stack=list(bom.tree.children)
    excluded={PartClass.ASSEMBLY,PartClass.PHANTOM,PartClass.DOCUMENT}
    while stack:
        node=stack.pop(); stack.extend(node.children)
        if node.standard_cost is not None and node.part_class not in excluded:
            ext=Decimal(str(node.extended_quantity))*Decimal(str(node.standard_cost)); material_total+=ext
            material_lines.append(MaterialLine(part_number=node.part_number,extended_quantity=node.extended_quantity,standard_cost=node.standard_cost,extended_cost=money(ext)))
    part=(await session.execute(select(Part).where(Part.part_number==part_number.upper()))).scalar_one()
    rev=(await session.execute(select(PartRevision).where(PartRevision.part_id==part.id).order_by(PartRevision.released_at.desc().nullslast(),PartRevision.created_at.desc()))).scalars().first()
    if rev is None: raise ToolError(f"{part_number} has no revision.")
    ops=(await session.execute(select(Operation).where(Operation.root_revision_id==rev.id).order_by(Operation.op_seq))).scalars().all()
    rates={r.work_center:Decimal(str(r.hourly_rate)) for r in (await session.execute(select(WorkCentreRate))).scalars().all()}
    labour=[]; labour_total=Decimal(0); batch=Decimal(str(batch_size))
    for op in ops:
        minutes=Decimal(str(op.run_minutes))+Decimal(str(op.setup_minutes))/batch; rate=rates.get(op.work_center,Decimal(0)); cost=minutes/Decimal(60)*rate; labour_total+=cost
        labour.append(LabourLine(operation_seq=op.op_seq,work_center=op.work_center,minutes_per_unit=float(minutes),hourly_rate=float(rate),cost=money(cost)))
    return CostRollup(part_number=part.part_number,revision=rev.revision,batch_size=batch_size,material_cost=money(material_total),labour_cost=money(labour_total),total_cost=money(material_total+labour_total),materials=material_lines,labour=labour)

async def capture_snapshot(session: AsyncSession, part_number: str, batch_size: float, captured_by=None, baseline_id=None, eco_id=None, commit: bool=True):
    result=await rollup_cost(session,part_number,batch_size); part=(await session.execute(select(Part).where(Part.part_number==result.part_number))).scalar_one(); rev=(await session.execute(select(PartRevision).where(PartRevision.part_id==part.id,PartRevision.revision==result.revision))).scalar_one()
    row=CostRollupSnapshot(part_id=part.id,revision_id=rev.id,baseline_id=baseline_id,eco_id=eco_id,material_cost=result.material_cost,labour_cost=result.labour_cost,total_cost=result.total_cost,batch_size=batch_size,details=result.model_dump(mode="json"),captured_by=captured_by); session.add(row)
    if commit: await session.commit()
    else: await session.flush()
    return row

async def variance_report(session: AsyncSession, fiscal_year: int) -> list[VarianceRow]:
    centres=(await session.execute(select(CostCentre).order_by(CostCentre.code))).scalars().all(); rows=[]
    for c in centres:
        b=Decimal(str(await session.scalar(select(func.coalesce(func.sum(Budget.amount),0)).where(Budget.cost_centre_id==c.id,Budget.fiscal_year==fiscal_year)) or 0)); k=Decimal(str(await session.scalar(select(func.coalesce(func.sum(Commitment.amount),0)).where(Commitment.cost_centre_id==c.id,func.extract("year",Commitment.occurred_on)==fiscal_year)) or 0)); a=Decimal(str(await session.scalar(select(func.coalesce(func.sum(Actual.amount),0)).where(Actual.cost_centre_id==c.id,func.extract("year",Actual.occurred_on)==fiscal_year)) or 0)); rows.append(VarianceRow(cost_centre=c.code,budget=float(b),commitments=float(k),actuals=float(a),variance=float(b-k-a)))
    return rows
