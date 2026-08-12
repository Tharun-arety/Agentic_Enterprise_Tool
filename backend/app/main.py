"""FastAPI entrypoint.

    .venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --port 8000

`POST /api/chat` streams Server-Sent Events. Each frame is tagged with an SSE
`event:` name and carries a JSON payload:

    agent_state  {"agent": "PDM Agent", "status": "delegating"}
    tool_result  {"tool": "get_bom_structure", "payload": {...}}
    token        {"text": "..."}
    final        {"text": "...", "intent": "pdm", "tool_calls": [...]}
    error        {"message": "..."}

The structured `tool_result` payload is what drives the BOM tree and the metrics
chart; `token` drives the chat bubble. Keeping them as separate frames is what
lets the UI render real data without parsing prose.

The thin REST reads exist so the dashboard can paint on first load without
spending a model call.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agents.graph import run_agent
from app.agents.schemas import ChatRequest, ErrorFrame, FinalFrame
from app.core.config import get_settings
from app.core.db import dispose_engine, get_session, get_session_factory
from app.core.embeddings import get_embedding_provider
from app.core.llm import StubModelClient, get_model_client
from app.core.router import router as governance_router
from app.domains.identity.router import router as identity_router
from app.domains.ecm.router import router as ecm_router
from app.domains.knowledge.schemas import KnowledgeResponse
from app.domains.knowledge.service import search_engineering_knowledge
from app.domains.pdm.router import router as pdm_router
from app.domains.qms.router import router as qms_router
from app.domains.procurement.router import router as procurement_router
from app.domains.crm.router import router as crm_router
from app.domains.programs.router import router as programs_router
from app.domains.assets.router import router as assets_router
from app.domains.resources.router import router as resources_router
from app.domains.controlling.router import router as controlling_router
from app.domains.knowledge.router import router as knowledge_router
from app.agents.router import router as agent_runs_router
from app.evals.router import router as evals_router
from app.domains.showcase.router import router as showcase_router
from app.core.deps import current_principal
from app.core.middleware import RequestContextMiddleware
from app.domains.backoffice.router import router as backoffice_router
from app.domains.backoffice.adapters import ErpnextBackofficeAdapter, LocalBackofficeAdapter
from app.domains.backoffice.integration import queue_depth
from app.tools.registry import ToolError

logging.basicConfig(
    level=logging.INFO, format="%(levelname)-8s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Resolve both providers at startup so their warnings appear in the log
    # once, at boot, rather than on a random first request.
    provider = get_embedding_provider()
    client = get_model_client()
    logger.info(
        "Magnotherm backend ready. embeddings=%s semantic=%s model_client=%s",
        provider.name,
        provider.is_semantic,
        type(client).__name__,
    )
    if not settings.has_openai_key:
        logger.warning(
            "OPENAI_API_KEY is not set. /api/chat will answer from the stub "
            "client and knowledge search is not semantically ranked."
        )
    if not settings.has_production_jwt_secret:
        logger.warning(
            "JWT_SECRET is the built-in development value, which is public. "
            "Anyone can mint a token for any role. Set JWT_SECRET in "
            "backend/.env before this is reachable by anyone but you."
        )
    yield
    await dispose_engine()


app = FastAPI(
    title="Magnotherm Agentic Toolchain",
    version="0.1.0",
    description="PDM, QMS and engineering-knowledge access for magnetocaloric systems.",
    lifespan=lifespan,
)
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app, include_in_schema=False)

app.add_middleware(
    CORSMiddleware,
    # Scoped to known origins rather than "*", because the SSE endpoint is a
    # streaming POST and this is the boundary worth keeping tight.
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)

app.include_router(identity_router)
app.include_router(governance_router)
app.include_router(pdm_router)
app.include_router(ecm_router)
app.include_router(qms_router)
app.include_router(procurement_router)
app.include_router(crm_router)
app.include_router(programs_router)
app.include_router(assets_router)
app.include_router(resources_router)
app.include_router(controlling_router)
app.include_router(backoffice_router)
app.include_router(knowledge_router)
app.include_router(agent_runs_router)
app.include_router(evals_router)
app.include_router(showcase_router)


# --------------------------------------------------------------------------
# Health / meta
# --------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    embedding_provider: str
    semantic_search: bool
    model_client: str
    live_model: bool
    # False while the built-in development signing key is in use. Surfaced
    # rather than hidden, for the same reason the stub-model flag is: a
    # degraded mode that looks identical to the real thing is the dangerous one.
    secure_tokens: bool
    adapter: str
    adapter_status: str
    adapter_detail: str | None = None
    last_synchronization: str | None = None
    queue_depth: int = 0
    degraded_mode: bool = False


@app.get("/api/health", response_model=HealthResponse)
async def health(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    provider = get_embedding_provider()
    client = get_model_client()
    settings=get_settings()
    selected = ErpnextBackofficeAdapter() if settings.backoffice_adapter.lower()=="erpnext" else LocalBackofficeAdapter(session)
    adapter_health=await selected.health()
    degraded=adapter_health.status!="ok"
    active="local" if degraded and settings.backoffice_adapter.lower()=="erpnext" else adapter_health.adapter
    return HealthResponse(
        status="ok",
        embedding_provider=provider.name,
        semantic_search=provider.is_semantic,
        model_client=type(client).__name__,
        live_model=not isinstance(client, StubModelClient),
        secure_tokens=get_settings().has_production_jwt_secret,
        adapter=active,
        adapter_status="degraded" if degraded else adapter_health.status,
        adapter_detail=adapter_health.detail,
        last_synchronization=adapter_health.last_sync_at.isoformat() if adapter_health.last_sync_at else None,
        queue_depth=await queue_depth(session),
        degraded_mode=degraded,
    )


# --------------------------------------------------------------------------
# REST reads (first-paint data; no model call)
# --------------------------------------------------------------------------


@app.get("/api/knowledge", response_model=KnowledgeResponse)
async def read_knowledge(
    q: str = "engineering change", limit: int = 5,
    session: AsyncSession = Depends(get_session),
    principal=Depends(current_principal),
) -> KnowledgeResponse:
    try:
        return await search_engineering_knowledge(session, q, max(1, min(limit, 10)))
    except ToolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --------------------------------------------------------------------------
# Agent chat (SSE)
# --------------------------------------------------------------------------


@app.post("/api/chat")
async def chat(request: ChatRequest, principal=Depends(current_principal)) -> EventSourceResponse:
    """Stream one agent turn as Server-Sent Events."""
    queue: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue()

    async def emit(event: str, payload: BaseModel) -> None:
        await queue.put((event, payload.model_dump_json()))

    async def drive() -> None:
        """Run the graph, then close the queue exactly once."""
        # A dedicated session rather than the request-scoped dependency: this
        # outlives the handler's return, because the response body is produced
        # lazily as the generator is consumed.
        try:
            async with get_session_factory()() as session:
                state = await run_agent(
                    session=session,
                    emit=emit,
                    user_message=request.message,
                    history=[m.model_dump() for m in request.history],
                    user_id=principal.user_id,
                )
            await queue.put(
                (
                    "final",
                    FinalFrame(
                        run_id=state.get("run_id"),
                        correlation_id=state.get("correlation_id"),
                        text=state.get("final_text", ""),
                        intent=(state.get("domains") or ["general"])[0],
                        domains=state.get("domains", []),
                        tool_calls=state.get("tool_calls", []),
                        citations=state.get("citations", []),
                        proposal_summaries=state.get("proposal_summaries", []),
                    ).model_dump_json(),
                )
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the client below
            logger.exception("Agent run failed")
            await queue.put(
                ("error", ErrorFrame(message=f"{type(exc).__name__}: {exc}").model_dump_json())
            )
        finally:
            await queue.put(None)  # sentinel: no more frames

    async def event_stream() -> AsyncIterator[dict[str, Any]]:
        task = asyncio.create_task(drive())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                yield {"event": event, "data": data}
        finally:
            # Covers client disconnect: without this the graph would keep
            # running (and keep spending tokens) after nobody is listening.
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return EventSourceResponse(event_stream())


# --------------------------------------------------------------------------
# Convenience: python -m app.main
# --------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app", host=settings.api_host, port=settings.api_port, reload=True
    )
