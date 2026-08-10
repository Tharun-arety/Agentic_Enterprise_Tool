"""Read-only domain tools for the second-level agents."""
from pydantic import BaseModel
from sqlalchemy import func,select
from app.domains.assets.models import AssetBooking,CalibrationCertificate,LabAsset
from app.domains.controlling.service import rollup_cost,variance_report
from app.domains.crm.models import DeployedUnit,FieldEvent,Opportunity
from app.domains.programs.models import Deliverable,Program,TrlGate,WorkPackage
from app.domains.resources.models import EngineerCapacity,ResourceAllocation
from app.tools.registry import ToolSpec,register
class Payload(BaseModel): data:list[dict]
def row(x): return {c.name:getattr(x,c.name) for c in x.__table__.columns}
async def crm(session): return Payload(data=[row(x) for x in (await session.execute(select(Opportunity))).scalars()]+[row(x) for x in (await session.execute(select(DeployedUnit))).scalars()])
async def programs(session): return Payload(data=[row(x) for x in (await session.execute(select(Program))).scalars()]+[row(x) for x in (await session.execute(select(TrlGate))).scalars()]+[row(x) for x in (await session.execute(select(Deliverable))).scalars()])
async def assets(session): return Payload(data=[row(x) for x in (await session.execute(select(CalibrationCertificate))).scalars()]+[row(x) for x in (await session.execute(select(AssetBooking))).scalars()])
async def resources(session):
    rows=(await session.execute(select(EngineerCapacity.user_id,EngineerCapacity.week_start,EngineerCapacity.available_hours,func.coalesce(func.sum(ResourceAllocation.allocated_hours),0)).outerjoin(ResourceAllocation,(ResourceAllocation.user_id==EngineerCapacity.user_id)&(ResourceAllocation.week_start==EngineerCapacity.week_start)).group_by(EngineerCapacity.id))).all(); return Payload(data=[{"user_id":str(u),"week_start":str(w),"available_hours":float(a),"allocated_hours":float(x)} for u,w,a,x in rows])
async def cost(session,part_number:str,batch_size:float=1): return rollup_cost(session,part_number,batch_size)
async def variance(session,fiscal_year:int): return Payload(data=[x.model_dump(mode="json") for x in await variance_report(session,fiscal_year)])
EMPTY={"type":"object","properties":{},"additionalProperties":False}
register(ToolSpec("get_crm_portfolio","Read opportunities, deployments and field context.",EMPTY,crm,"crm",result_schema=Payload))
register(ToolSpec("get_program_progress","Read work packages, TRL gates and deliverables.",EMPTY,programs,"programs",result_schema=Payload))
register(ToolSpec("get_asset_readiness","Read calibration due dates and booking conflicts.",EMPTY,assets,"assets",result_schema=Payload))
register(ToolSpec("get_resource_loading","Read engineer capacity and allocations.",EMPTY,resources,"resources",result_schema=Payload))
register(ToolSpec("rollup_mbom_cost","Calculate effective material and operation labour cost.",{"type":"object","properties":{"part_number":{"type":"string"},"batch_size":{"type":"number","exclusiveMinimum":0}},"required":["part_number"],"additionalProperties":False},cost,"controlling",result_schema=__import__("app.domains.controlling.schemas",fromlist=["CostRollup"]).CostRollup,sensitivity="financial"))
register(ToolSpec("get_budget_variance","Report budget minus commitments minus actuals.",{"type":"object","properties":{"fiscal_year":{"type":"integer"}},"required":["fiscal_year"],"additionalProperties":False},variance,"controlling",result_schema=Payload,sensitivity="financial"))
