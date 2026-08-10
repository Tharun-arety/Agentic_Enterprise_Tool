from typing import Annotated
from fastapi import APIRouter,Depends,HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.models import AgentRun,ToolInvocation
from app.core.db import get_session
from app.core.deps import current_principal
from app.core.principal import Principal
router=APIRouter(prefix="/api/agent-runs",tags=["agents"])
@router.get("")
async def runs(principal:Annotated[Principal,Depends(current_principal)],session:Annotated[AsyncSession,Depends(get_session)]): return [{"id":str(x.id),"correlation_id":str(x.correlation_id),"status":x.status,"domains":x.routed_domains,"model":x.model_snapshot,"duration_ms":x.duration_ms,"started_at":x.started_at} for x in (await session.execute(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(100))).scalars()]
@router.get("/{run_id}")
async def run(run_id:str,principal:Annotated[Principal,Depends(current_principal)],session:Annotated[AsyncSession,Depends(get_session)]):
    row=await session.get(AgentRun,__import__("uuid").UUID(run_id))
    if not row: raise HTTPException(404,"Agent run not found.")
    tools=(await session.execute(select(ToolInvocation).where(ToolInvocation.run_id==row.id).order_by(ToolInvocation.created_at))).scalars(); return {"run":{"id":str(row.id),"status":row.status,"question":row.question,"domains":row.routed_domains,"outcome":row.outcome},"tools":[{"name":x.tool_name,"domain":x.domain,"arguments":x.arguments,"result":x.result,"duration_ms":x.duration_ms} for x in tools]}
