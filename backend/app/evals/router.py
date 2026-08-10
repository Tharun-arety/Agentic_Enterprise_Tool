from typing import Annotated
from fastapi import APIRouter,Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.evals.models import EvalCaseResult,EvalRun
from app.evals.runner import run_offline
router=APIRouter(prefix="/api/evals",tags=["evals"])
@router.get("")
async def runs(principal:Annotated[Principal,Depends(require_roles(Role.ADMIN,Role.ENGINEER))],session:Annotated[AsyncSession,Depends(get_session)]): return [{"id":str(x.id),"suite":x.suite,"status":x.status,"passed":x.passed,"failed":x.failed,"metrics":x.metrics,"started_at":x.started_at} for x in (await session.execute(select(EvalRun).order_by(EvalRun.started_at.desc()))).scalars()]
@router.post("/offline")
async def execute(principal:Annotated[Principal,Depends(require_roles(Role.ADMIN))],session:Annotated[AsyncSession,Depends(get_session)]):
    cases=run_offline(); run=EvalRun(suite="offline",status="passed" if all(x.passed for x in cases) else "failed",passed=sum(x.passed for x in cases),failed=sum(not x.passed for x in cases),metrics={"pass_rate":sum(x.passed for x in cases)/len(cases)}); session.add(run); await session.flush()
    for c in cases: session.add(EvalCaseResult(run_id=run.id,case_name=c.name,category=c.category,passed=c.passed,score=c.score,latency_ms=0,detail=c.detail,trajectory=[]))
    await session.commit(); return {"run_id":str(run.id),"status":run.status,"cases":[c.__dict__ for c in cases]}
