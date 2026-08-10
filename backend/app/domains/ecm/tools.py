"""ECM tools, registered for both the agent graph and the MCP server.

The write tools here are the reason the proposal spine exists. An agent that
can raise a change request is useful; an agent that can release one on its own
authority is a liability. Both go through the queue, and the roles they demand
differ because the acts differ: raising a request is engineering work, releasing
an order is the systems-engineering authority to move the configuration.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal import SYSTEM_PRINCIPAL, Principal
from app.core.schemas import ProposalPreview, ProposedChange
from app.domains.ecm.models import ChangeOrigin, ChangePriority
from app.domains.ecm.release import release_change_order
from app.domains.ecm.service import (
    create_change_request,
    get_change_order,
    get_change_request,
    list_change_requests,
    reassess,
)
from app.domains.identity.models import Role
from app.tools.registry import ToolSpec, register

# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

register(
    ToolSpec(
        name="get_change_request",
        domain="ecm",
        description=(
            "Retrieve one engineering change request (ECR) by number: the "
            "problem, the proposed solution, which parts it affects, every "
            "Change Control Board vote cast so far, whether quorum is met, and "
            "the impact assessment. Use this for any question about a specific "
            "change. Numbers look like ECR-26-001."
        ),
        parameters={
            "type": "object",
            "properties": {
                "number": {
                    "type": "string",
                    "description": "The ECR number, e.g. 'ECR-26-001'.",
                }
            },
            "required": ["number"],
            "additionalProperties": False,
        },
        handler=get_change_request,
    )
)


register(
    ToolSpec(
        name="list_change_requests",
        domain="ecm",
        description=(
            "List engineering change requests, most recent first, optionally "
            "filtered by status (Draft, Submitted, Under review, Approved, "
            "Rejected, Converted, Cancelled). Use this for questions about what "
            "changes are in flight or waiting on the board."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Optional status filter, e.g. 'Under review'.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=list_change_requests,
    )
)


register(
    ToolSpec(
        name="get_change_order",
        domain="ecm",
        description=(
            "Retrieve one engineering change order (ECO) by number: its line "
            "items, effectivity, status, and any change notice issued for it. "
            "Numbers look like ECO-26-001."
        ),
        parameters={
            "type": "object",
            "properties": {
                "number": {
                    "type": "string",
                    "description": "The ECO number, e.g. 'ECO-26-001'.",
                }
            },
            "required": ["number"],
            "additionalProperties": False,
        },
        handler=get_change_order,
    )
)


async def _assess_impact(session: AsyncSession, number: str):
    """Recompute a request's impact, without attaching a new assessment."""
    return await reassess(session, actor=SYSTEM_PRINCIPAL, number=number, commit=False)


register(
    ToolSpec(
        name="assess_change_impact",
        domain="ecm",
        description=(
            "Work out everything a proposed change would reach: which "
            "assemblies contain the affected parts, which finished products sit "
            "above them, which drawings and work instructions need reissuing, "
            "which recorded test evidence stops being valid and needs "
            "re-running, which captured baselines contain the parts, and the "
            "current standard cost. Use this before recommending for or against "
            "a change. Anything it could not determine is listed under 'gaps' — "
            "report those, do not treat them as nothing."
        ),
        parameters={
            "type": "object",
            "properties": {
                "number": {
                    "type": "string",
                    "description": "The ECR number to assess, e.g. 'ECR-26-001'.",
                }
            },
            "required": ["number"],
            "additionalProperties": False,
        },
        handler=_assess_impact,
    )
)


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------


async def _preview_raise_ecr(
    session: AsyncSession,
    title: str,
    problem_statement: str,
    proposed_solution: str,
    affected_part_numbers: list[str],
    origin: str = ChangeOrigin.RND.value,
    priority: str = ChangePriority.NORMAL.value,
) -> ProposalPreview:
    """Draft the request and describe it, then discard the draft."""
    request = await create_change_request(
        session,
        actor=SYSTEM_PRINCIPAL,
        title=title,
        problem_statement=problem_statement,
        proposed_solution=proposed_solution,
        affected_part_numbers=affected_part_numbers,
        origin=ChangeOrigin(origin),
        priority=ChangePriority(priority),
        commit=False,
    )
    assessment = request.latest_assessment
    await session.rollback()

    changes = [
        ProposedChange(
            kind="add",
            target="ChangeRequest",
            field="title",
            after=title,
        ),
        *(
            ProposedChange(kind="modify", target=f"Part {part}", field="affected by")
            for part in request.affected_part_numbers
        ),
    ]
    warnings = list(assessment.findings.gaps) if assessment else []
    if assessment and assessment.findings.revalidation_required:
        warnings.append(
            "Test evidence on "
            + ", ".join(
                evidence.serial_number
                for evidence in assessment.findings.revalidation_required
            )
            + " would need re-validating."
        )

    return ProposalPreview(
        summary=(
            f"Raise a change request over "
            f"{', '.join(request.affected_part_numbers)}: {title}. "
            + (assessment.summary if assessment else "")
        ),
        entity_type="ChangeRequest",
        entity_ref=None,
        changes=changes,
        warnings=warnings,
    )


async def _apply_raise_ecr(
    session: AsyncSession,
    *,
    actor: Principal,
    title: str,
    problem_statement: str,
    proposed_solution: str,
    affected_part_numbers: list[str],
    origin: str = ChangeOrigin.RND.value,
    priority: str = ChangePriority.NORMAL.value,
    **_: object,
) -> dict:
    request = await create_change_request(
        session,
        actor=actor,
        title=title,
        problem_statement=problem_statement,
        proposed_solution=proposed_solution,
        affected_part_numbers=affected_part_numbers,
        origin=ChangeOrigin(origin),
        priority=ChangePriority(priority),
        commit=False,
    )
    return {"number": request.number, "status": request.status.value}


register(
    ToolSpec(
        name="raise_change_request",
        domain="ecm",
        description=(
            "Raise an engineering change request against one or more parts, "
            "with an impact assessment attached automatically. Use this when "
            "asked to propose, draft or open a change. The request is prepared "
            "for a person to approve rather than created directly, and once "
            "created it still has to be submitted to the Change Control Board."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "One line, what changes."},
                "problem_statement": {
                    "type": "string",
                    "description": "What is wrong today, and how it is known.",
                },
                "proposed_solution": {
                    "type": "string",
                    "description": "What to do about it.",
                },
                "affected_part_numbers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Part numbers the change touches.",
                },
                "origin": {
                    "type": "string",
                    "enum": [origin.value for origin in ChangeOrigin],
                },
                "priority": {
                    "type": "string",
                    "enum": [priority.value for priority in ChangePriority],
                },
            },
            "required": [
                "title",
                "problem_statement",
                "proposed_solution",
                "affected_part_numbers",
            ],
            "additionalProperties": False,
        },
        handler=_preview_raise_ecr,
        applier=_apply_raise_ecr,
        required_role=Role.ENGINEER,
    )
)


async def _preview_release_eco(session: AsyncSession, number: str) -> ProposalPreview:
    result = await release_change_order(
        session, actor=SYSTEM_PRINCIPAL, number=number, commit=False
    )
    await session.rollback()

    return ProposalPreview(
        summary=(
            f"Release {result.change_order_number}: "
            + "; ".join(
                f"{rev.part_number} {rev.from_revision} to {rev.to_revision}"
                for rev in result.revisions_created
            )
            + f". {result.edges_added} line(s) added, {result.edges_removed} "
            f"removed, {result.edges_modified} changed. Notice "
            f"{result.notice_number} would be issued."
        ),
        entity_type="ChangeOrder",
        entity_ref=result.change_order_number,
        changes=[
            ProposedChange(
                kind="modify",
                target=f"Part {rev.part_number}",
                field="revision",
                before=rev.from_revision,
                after=rev.to_revision,
            )
            for rev in result.revisions_created
        ],
        warnings=result.warnings,
    )


async def _apply_release_eco(
    session: AsyncSession, *, actor: Principal, number: str, **_: object
) -> dict:
    result = await release_change_order(
        session, actor=actor, number=number, commit=False
    )
    return result.model_dump(mode="json")


register(
    ToolSpec(
        name="release_change_order",
        domain="ecm",
        description=(
            "Release an approved engineering change order: issue new revisions "
            "of every affected assembly, carry their structure forward with the "
            "order's line items applied, capture a configuration baseline, issue "
            "the change notice, and index the change into the knowledge corpus. "
            "This moves the released configuration, so it is prepared for a "
            "person holding systems-engineering authority to approve. It will "
            "refuse if the underlying request has not cleared the board."
        ),
        parameters={
            "type": "object",
            "properties": {
                "number": {
                    "type": "string",
                    "description": "The ECO number to release, e.g. 'ECO-26-001'.",
                }
            },
            "required": ["number"],
            "additionalProperties": False,
        },
        handler=_preview_release_eco,
        applier=_apply_release_eco,
        required_role=Role.SYSTEMS_ENGINEERING,
    )
)
