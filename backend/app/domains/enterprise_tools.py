"""Read-only domain tools for the second-level agents.

Two rules here, both learned the hard way.

**The reads come from each domain's `queries` module, not from a local copy.**
These tools used to build their own payloads with a generic `row()` helper that
dumped every column, so the agent answered with
`work_package c6cd00e3-2d04-42d8-a26a-777217ac95cb` long after the screens had
learned to say "WP4 — ECLIPSE field validation". Same data, two code paths, one
of them forgotten.

**Payloads are grouped by what the records are.** They used to be concatenated
into one flat `data` list — programmes, gates and deliverables in a single
array with no field telling them apart — which left the model to infer the
schema from the keys present on each object.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import enum_text as _text
from app.core.proposals import AgentProposal, ProposalStatus
from app.domains.assets import queries as asset_queries
from app.domains.controlling.schemas import CostRollup
from app.domains.controlling.service import rollup_cost, variance_report
from app.domains.crm import queries as crm_queries
from app.domains.ecm.models import EcrStatus
from app.domains.ecm.service import list_change_requests
from app.domains.procurement.service import supply_risk
from app.domains.programs import queries as program_queries
from app.domains.qms.models import NcrStatus
from app.domains.qms.ncr import list_non_conformances
from app.domains.resources import queries as resource_queries
from app.tools.registry import ToolSpec, register

EMPTY: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


# --------------------------------------------------------------------------
# Domain reads
# --------------------------------------------------------------------------


class CrmPortfolio(BaseModel):
    opportunities: list[dict] = Field(default_factory=list)
    deployed_units: list[dict] = Field(default_factory=list)
    field_history: list[dict] = Field(default_factory=list)


class ProgramProgress(BaseModel):
    programmes: list[dict] = Field(default_factory=list)
    work_packages: list[dict] = Field(default_factory=list)
    trl_gates: list[dict] = Field(default_factory=list)
    deliverables: list[dict] = Field(default_factory=list)


class AssetReadiness(BaseModel):
    calibration: list[dict] = Field(default_factory=list)
    bookings: list[dict] = Field(default_factory=list)


class ResourceLoading(BaseModel):
    capacity: list[dict] = Field(default_factory=list)
    timesheets: list[dict] = Field(default_factory=list)


class Rows(BaseModel):
    data: list[dict] = Field(default_factory=list)


async def crm(session: AsyncSession) -> CrmPortfolio:
    return CrmPortfolio(
        opportunities=await crm_queries.list_opportunities(session),
        deployed_units=await crm_queries.list_deployed_units(session),
        field_history=await crm_queries.list_field_history(session),
    )


async def programs(session: AsyncSession) -> ProgramProgress:
    return ProgramProgress(
        programmes=await program_queries.list_programmes(session),
        work_packages=await program_queries.list_work_packages(session),
        trl_gates=await program_queries.list_trl_gates(session),
        deliverables=await program_queries.list_deliverables(session),
    )


async def assets(session: AsyncSession) -> AssetReadiness:
    return AssetReadiness(
        calibration=await asset_queries.list_calibration(session),
        bookings=await asset_queries.list_bookings(session),
    )


async def resources(session: AsyncSession) -> ResourceLoading:
    return ResourceLoading(
        capacity=await resource_queries.list_capacity(session),
        timesheets=await resource_queries.list_timesheets(session),
    )


async def cost(session: AsyncSession, part_number: str, batch_size: float = 1):
    return rollup_cost(session, part_number, batch_size)


async def variance(session: AsyncSession, fiscal_year: int) -> Rows:
    return Rows(data=[x.model_dump(mode="json") for x in await variance_report(session, fiscal_year)])


# --------------------------------------------------------------------------
# What needs attention
# --------------------------------------------------------------------------


class AttentionItem(BaseModel):
    """One thing a person may need to act on."""

    severity: str  # "urgent" | "high" | "watch"
    domain: str
    reference: str
    summary: str
    detail: str | None = None
    owner: str | None = None
    href: str | None = None


class AttentionReport(BaseModel):
    generated_at: datetime
    urgent_count: int
    high_count: int
    watch_count: int
    items: list[AttentionItem] = Field(default_factory=list)


#: Ranking used to sort the report and to describe it back to the reader.
_SEVERITY_ORDER = {"urgent": 0, "high": 1, "watch": 2}


async def attention(session: AsyncSession) -> AttentionReport:
    """Everything currently asking for a decision, across every domain.

    This exists because the agent could not answer "what is urgent right now".
    Each domain could report its own state, but nothing ranked across them, so
    the router picked two plausible domains, called nothing, and said the
    question was not determinable — the one answer that is never true when
    there is an urgent change request sitting on the board.
    """
    items: list[AttentionItem] = []

    # Change requests still in flight, urgent ones first.
    open_states = {_text(state) for state in (EcrStatus.DRAFT, EcrStatus.SUBMITTED, EcrStatus.UNDER_REVIEW)}
    for request in await list_change_requests(session):
        if _text(request.status) not in open_states:
            continue
        priority = _text(request.priority)
        quorum = request.quorum
        missing = ", ".join(quorum.missing_seats) if quorum and quorum.missing_seats else ""
        items.append(
            AttentionItem(
                severity={"urgent": "urgent", "high": "high"}.get(priority.lower(), "watch"),
                domain="Engineering change",
                reference=request.number,
                summary=f"{priority} change request awaiting the board: {request.title}",
                detail=f"Status {_text(request.status)}."
                + (f" Seats still to vote: {missing}." if missing else ""),
                owner=request.originator_label,
                href="/ecm",
            )
        )

    # Open non-conformances.
    for ncr in await list_non_conformances(session):
        if _text(ncr.status) == _text(NcrStatus.CLOSED):
            continue
        severity = _text(ncr.severity)
        scope = ncr.lot_number or ncr.serial_number or ncr.part_number or "unscoped"
        items.append(
            AttentionItem(
                severity={"critical": "urgent", "major": "high"}.get(severity.lower(), "watch"),
                domain="Quality",
                reference=ncr.number,
                summary=f"{severity} non-conformance open: {ncr.title}",
                detail=f"Scope {scope}."
                + (f" Affects {', '.join(ncr.affected_units)}." if ncr.affected_units else ""),
                owner=ncr.raised_by_label,
                href="/qms",
            )
        )

    # Calibration that has lapsed or is about to.
    for certificate in await asset_queries.list_calibration(session):
        if not (certificate["overdue"] or certificate["due_soon"]):
            continue
        days = certificate["days_remaining"]
        items.append(
            AttentionItem(
                severity="urgent" if certificate["overdue"] else "watch",
                domain="Lab assets",
                reference=certificate["asset_tag"],
                summary=(
                    f"Calibration lapsed on {certificate['asset_name']}"
                    if certificate["overdue"]
                    else f"Calibration due on {certificate['asset_name']}"
                ),
                detail=(
                    f"Certificate {certificate['certificate_number']} "
                    + (f"expired {abs(days)} days ago." if days < 0 else f"expires in {days} days.")
                ),
                href="/assets",
            )
        )

    # Stock that will not cover the next build.
    for position in await supply_risk(session):
        if not position["low_stock"]:
            continue
        lead = position.get("lead_time_days")
        items.append(
            AttentionItem(
                severity="urgent" if (lead or 0) >= 60 else "high",
                domain="Procurement",
                reference=position["part_number"],
                # The identifier is repeated inside the sentence on purpose.
                # Left only in `reference`, the synthesiser reported "an
                # unspecified item has dropped below its reorder level", which
                # is useless to a buyer. Every summary has to stand alone.
                summary=(
                    f"{position['part_number']} available stock below reorder level "
                    f"({position['available']:g} of {position['reorder_level']:g})"
                ),
                detail=f"{lead}-day lead time." if lead else None,
                href="/procurement",
            )
        )

    # Engineers booked past capacity.
    for week in await resource_queries.list_capacity(session):
        if not week["overloaded"]:
            continue
        over = week["allocated_hours"] - week["available_hours"]
        items.append(
            AttentionItem(
                severity="high",
                domain="Resourcing",
                reference=f"{week['engineer']} · week of {week['week_start']}",
                summary=f"Booked {over:g} hours beyond capacity",
                detail=", ".join(
                    f"{entry['work_package']} {entry['hours']:g}h" for entry in week["packages"]
                )
                or None,
                owner=week["engineer"],
                href="/resources",
            )
        )

    # Agent proposals nobody has ruled on.
    pending = (
        await session.execute(
            select(AgentProposal)
            .where(AgentProposal.status == ProposalStatus.PENDING)
            .order_by(AgentProposal.created_at)
        )
    ).scalars().all()
    for proposal in pending:
        items.append(
            AttentionItem(
                severity="high",
                domain="Approvals",
                reference=proposal.tool_name,
                summary=f"Agent action waiting for {proposal.required_role}: {proposal.summary}",
                detail=f"Proposed by {proposal.proposed_by_agent}.",
                href="/approval-inbox",
            )
        )

    items.sort(key=lambda item: (_SEVERITY_ORDER.get(item.severity, 3), item.domain, item.reference))
    return AttentionReport(
        generated_at=datetime.now(timezone.utc),
        urgent_count=sum(1 for item in items if item.severity == "urgent"),
        high_count=sum(1 for item in items if item.severity == "high"),
        watch_count=sum(1 for item in items if item.severity == "watch"),
        items=items,
    )


class PendingProposal(BaseModel):
    proposed_by_agent: str
    tool_name: str
    summary: str
    required_role: str
    created_at: datetime
    changes: list[dict] = Field(default_factory=list)


class PendingProposals(BaseModel):
    count: int
    proposals: list[PendingProposal] = Field(default_factory=list)


async def pending_proposals(session: AsyncSession) -> PendingProposals:
    """The approval queue, read-only.

    Deliberately a read. Approving and rejecting stay off the tool registry
    entirely — an agent that could approve its own proposal would make the
    whole write spine decorative, and one of the offline evals asserts those
    operations are unreachable.
    """
    rows = (
        await session.execute(
            select(AgentProposal)
            .where(AgentProposal.status == ProposalStatus.PENDING)
            .order_by(AgentProposal.created_at)
        )
    ).scalars().all()
    return PendingProposals(
        count=len(rows),
        proposals=[
            PendingProposal(
                proposed_by_agent=row.proposed_by_agent,
                tool_name=row.tool_name,
                summary=row.summary,
                required_role=row.required_role,
                created_at=row.created_at,
                changes=(row.preview or {}).get("changes", []),
            )
            for row in rows
        ],
    )


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

register(
    ToolSpec(
        "get_operational_attention",
        (
            "What needs a decision right now, across every domain, ranked by "
            "severity. Use this for any question about what is urgent, what is "
            "outstanding, what is pending, what is overdue, what needs "
            "attention, or what someone should do next — it is the only tool "
            "that ranks across domains."
        ),
        EMPTY,
        attention,
        "operations",
        result_schema=AttentionReport,
    )
)
register(
    ToolSpec(
        "list_pending_proposals",
        (
            "Agent-proposed changes waiting for a person to approve or reject. "
            "Use this when asked what the agents have prepared, what is in the "
            "approval queue, or what is awaiting sign-off."
        ),
        EMPTY,
        pending_proposals,
        "operations",
        result_schema=PendingProposals,
    )
)
register(
    ToolSpec(
        "get_crm_portfolio",
        "Read opportunities, deployed units at customer sites, and field event history.",
        EMPTY,
        crm,
        "crm",
        result_schema=CrmPortfolio,
    )
)
register(
    ToolSpec(
        "get_program_progress",
        "Read funded programmes, work packages, TRL readiness gates and consortium deliverables.",
        EMPTY,
        programs,
        "programs",
        result_schema=ProgramProgress,
    )
)
register(
    ToolSpec(
        "get_asset_readiness",
        "Read instrument calibration validity and rig bookings.",
        EMPTY,
        assets,
        "assets",
        result_schema=AssetReadiness,
    )
)
register(
    ToolSpec(
        "get_resource_loading",
        "Read engineer capacity, allocations and booked time by week.",
        EMPTY,
        resources,
        "resources",
        result_schema=ResourceLoading,
    )
)
register(
    ToolSpec(
        "rollup_mbom_cost",
        "Calculate effective material and operation labour cost.",
        {
            "type": "object",
            "properties": {
                "part_number": {"type": "string"},
                "batch_size": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["part_number"],
            "additionalProperties": False,
        },
        cost,
        "controlling",
        result_schema=CostRollup,
        sensitivity="financial",
    )
)
register(
    ToolSpec(
        "get_budget_variance",
        "Report budget minus commitments minus actuals.",
        {
            "type": "object",
            "properties": {"fiscal_year": {"type": "integer"}},
            "required": ["fiscal_year"],
            "additionalProperties": False,
        },
        variance,
        "controlling",
        result_schema=Rows,
        sensitivity="financial",
    )
)
