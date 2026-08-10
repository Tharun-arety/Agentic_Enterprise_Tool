"""QMS tools, registered for both the agent graph and the MCP server."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal import SYSTEM_PRINCIPAL, Principal
from app.core.schemas import ProposalPreview, ProposedChange
from app.domains.identity.models import Role
from app.domains.qms import ncr as ncr_service
from app.domains.qms.models import NcrSeverity, NcrSource
from app.domains.qms.service import (
    get_unit_genealogy,
    query_qms_test_metrics,
    trace_lot,
)
from app.tools.registry import ToolSpec, register

register(
    ToolSpec(
        name="query_qms_test_metrics",
        domain="qms",
        description=(
            "Retrieve the time-series lab test history for a physical unit's "
            "serial number, with per-metric min/max/mean/latest summaries, the "
            "acceptance limits that were applied, and the pass/fail verdict of "
            "each reading. Metrics are temperature_span_delta_K, "
            "pressure_drop_mbar, magnetization_cycles_hz and cooling_capacity_W. "
            "Use this for any question about measured performance, test results "
            "or quality trends. Example serial: ECL-M-104."
        ),
        parameters={
            "type": "object",
            "properties": {
                "serial_number": {
                    "type": "string",
                    "description": "The unit serial number, e.g. 'ECL-M-104'.",
                }
            },
            "required": ["serial_number"],
            "additionalProperties": False,
        },
        handler=query_qms_test_metrics,
    )
)


register(
    ToolSpec(
        name="get_unit_genealogy",
        domain="qms",
        description=(
            "Retrieve what one physical unit was actually built from: every "
            "component, the revision fitted, and the material lot it came from, "
            "including through serialised sub-assemblies. This is the as-built "
            "record for that individual article, which is not the same as the "
            "current bill of materials — use this when the question is about a "
            "specific serial number rather than about the product in general."
        ),
        parameters={
            "type": "object",
            "properties": {
                "serial_number": {
                    "type": "string",
                    "description": "The unit serial number, e.g. 'ECL-M-104'.",
                }
            },
            "required": ["serial_number"],
            "additionalProperties": False,
        },
        handler=get_unit_genealogy,
    )
)


register(
    ToolSpec(
        name="trace_lot",
        domain="qms",
        description=(
            "Find every unit containing a given lot or batch of material, "
            "including units that reach it through a serialised sub-assembly. "
            "Use this for recall and containment questions — 'which units have "
            "material from this batch?' — and when a supplier reports a problem "
            "with a delivery."
        ),
        parameters={
            "type": "object",
            "properties": {
                "lot_number": {
                    "type": "string",
                    "description": "The material lot or batch number, e.g. 'LFS-L-2405'.",
                }
            },
            "required": ["lot_number"],
            "additionalProperties": False,
        },
        handler=trace_lot,
    )
)


register(
    ToolSpec(
        name="get_non_conformance",
        domain="qms",
        description=(
            "Retrieve one non-conformance report by number: what was found, its "
            "severity and disposition, the corrective and preventive actions "
            "against it, every unit the problem reached, and the engineering "
            "change request it was escalated to if there is one. Numbers look "
            "like NCR-26-001."
        ),
        parameters={
            "type": "object",
            "properties": {
                "number": {"type": "string", "description": "e.g. 'NCR-26-001'."}
            },
            "required": ["number"],
            "additionalProperties": False,
        },
        handler=ncr_service.get_non_conformance,
    )
)


register(
    ToolSpec(
        name="list_non_conformances",
        domain="qms",
        description=(
            "List non-conformance reports, most recent first, optionally "
            "filtered by status (Open, Contained, Dispositioned, Closed). Use "
            "this for questions about outstanding quality problems."
        ),
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Optional status filter."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=ncr_service.list_non_conformances,
    )
)


# --------------------------------------------------------------------------
# Mutating
# --------------------------------------------------------------------------


async def _preview_raise_ncr(
    session: AsyncSession,
    title: str,
    description: str,
    source: str,
    severity: str = NcrSeverity.MINOR.value,
    serial_number: str | None = None,
    part_number: str | None = None,
    lot_number: str | None = None,
) -> ProposalPreview:
    result = await ncr_service.raise_non_conformance(
        session,
        actor=SYSTEM_PRINCIPAL,
        title=title,
        description=description,
        source=NcrSource(source),
        severity=NcrSeverity(severity),
        serial_number=serial_number,
        part_number=part_number,
        lot_number=lot_number,
        commit=False,
    )
    affected = list(result.affected_units)
    await session.rollback()

    warnings = []
    if affected:
        warnings.append(
            f"{len(affected)} unit(s) already built are affected: "
            + ", ".join(affected[:10])
            + ("…" if len(affected) > 10 else "")
        )

    scope = serial_number or part_number or lot_number
    return ProposalPreview(
        summary=f"Raise a {severity.lower()} non-conformance against {scope}: {title}",
        entity_type="NonConformance",
        entity_ref=scope,
        changes=[
            ProposedChange(kind="add", target="NonConformance", field="title", after=title)
        ],
        warnings=warnings,
    )


async def _apply_raise_ncr(
    session: AsyncSession,
    *,
    actor: Principal,
    title: str,
    description: str,
    source: str,
    severity: str = NcrSeverity.MINOR.value,
    serial_number: str | None = None,
    part_number: str | None = None,
    lot_number: str | None = None,
    **_: object,
) -> dict:
    result = await ncr_service.raise_non_conformance(
        session,
        actor=actor,
        title=title,
        description=description,
        source=NcrSource(source),
        severity=NcrSeverity(severity),
        serial_number=serial_number,
        part_number=part_number,
        lot_number=lot_number,
        commit=False,
    )
    return {"number": result.number, "affected_units": result.affected_units}


register(
    ToolSpec(
        name="raise_non_conformance",
        domain="qms",
        description=(
            "Raise a non-conformance report against a unit, a part, or a lot of "
            "material. Scope it to the lot when the problem is with a batch — "
            "the affected units are then worked out from the build records "
            "rather than guessed. Prepared for a person to approve rather than "
            "created directly."
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "One line, what is wrong."},
                "description": {
                    "type": "string",
                    "description": "What was found, and how.",
                },
                "source": {
                    "type": "string",
                    "enum": [source.value for source in NcrSource],
                },
                "severity": {
                    "type": "string",
                    "enum": [severity.value for severity in NcrSeverity],
                },
                "serial_number": {"type": "string"},
                "part_number": {"type": "string"},
                "lot_number": {"type": "string"},
            },
            "required": ["title", "description", "source"],
            "additionalProperties": False,
        },
        handler=_preview_raise_ncr,
        applier=_apply_raise_ncr,
        required_role=Role.QUALITY,
    )
)
