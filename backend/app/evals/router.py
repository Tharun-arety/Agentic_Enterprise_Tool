"""Evaluation endpoints: offline agent regression runs and their case results.

A run reports its cases, not just a pass count. A suite that says "12 passed,
1 failed" and will not say which one is a suite nobody acts on.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import require_roles
from app.core.principal import Principal
from app.domains.identity.models import Role
from app.evals.models import EvalCaseResult, EvalRun
from app.evals.runner import run_offline

router = APIRouter(prefix="/api/evals", tags=["evals"])


@router.get("")
async def runs(
    principal: Annotated[Principal, Depends(require_roles(Role.ADMIN, Role.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    run_rows = (
        await session.execute(select(EvalRun).order_by(EvalRun.started_at.desc()))
    ).scalars().all()
    case_rows = (
        await session.execute(
            select(EvalCaseResult).order_by(EvalCaseResult.category, EvalCaseResult.case_name)
        )
    ).scalars().all()

    cases_by_run: dict[str, list[dict[str, object]]] = {}
    for case in case_rows:
        cases_by_run.setdefault(str(case.run_id), []).append(
            {
                "case_name": case.case_name,
                "category": case.category,
                "passed": case.passed,
                "score": float(case.score),
                "detail": case.detail,
            }
        )

    return [
        {
            "id": str(run.id),
            "suite": run.suite,
            "status": run.status,
            "passed": run.passed,
            "failed": run.failed,
            "metrics": run.metrics,
            "started_at": run.started_at,
            "cases": cases_by_run.get(str(run.id), []),
        }
        for run in run_rows
    ]


@router.post("/offline")
async def execute(
    principal: Annotated[Principal, Depends(require_roles(Role.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    cases = run_offline()
    run = EvalRun(
        suite="offline",
        status="passed" if all(case.passed for case in cases) else "failed",
        passed=sum(case.passed for case in cases),
        failed=sum(not case.passed for case in cases),
        metrics={"pass_rate": sum(case.passed for case in cases) / len(cases)},
    )
    session.add(run)
    await session.flush()
    for case in cases:
        session.add(
            EvalCaseResult(
                run_id=run.id,
                case_name=case.name,
                category=case.category,
                passed=case.passed,
                score=case.score,
                latency_ms=0,
                detail=case.detail,
                trajectory=[],
            )
        )
    await session.commit()
    return {
        "run_id": str(run.id),
        "status": run.status,
        "cases": [case.__dict__ for case in cases],
    }
