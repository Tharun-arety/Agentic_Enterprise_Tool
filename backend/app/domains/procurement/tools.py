from pydantic import BaseModel
from app.domains.procurement.service import affected_units,supply_risk
from app.tools.registry import ToolSpec,register
class Payload(BaseModel): data:list[dict]
async def risk(session): return Payload(data=await supply_risk(session))
async def trace(session,lot_number:str): return Payload(data=await affected_units(session,lot_number))
register(ToolSpec("get_supply_risk","Show low-stock and lead-time exposure.",{"type":"object","properties":{},"additionalProperties":False},risk,"procurement",timeout_seconds=10,result_schema=Payload,sensitivity="internal"))
register(ToolSpec("trace_supplier_lot","Find every built unit containing an internal or supplier lot.",{"type":"object","properties":{"lot_number":{"type":"string"}},"required":["lot_number"],"additionalProperties":False},trace,"procurement",timeout_seconds=10,result_schema=Payload,sensitivity="controlled"))
