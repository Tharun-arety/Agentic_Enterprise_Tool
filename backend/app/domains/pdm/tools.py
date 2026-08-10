"""PDM tools, registered for both the agent graph and the MCP server."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.principal import SYSTEM_PRINCIPAL, Principal
from app.core.schemas import ProposalPreview, ProposedChange
from app.domains.identity.models import Role
from app.domains.pdm.baselines import diff_baselines
from app.domains.pdm.mbom import derive_mbom
from app.domains.pdm.service import (
    get_bom_structure,
    get_compliance_rollup,
    get_part_detail,
    get_where_used,
)
from app.tools.registry import ToolSpec, register

_BOM_TYPE_PROPERTY = {
    "type": "string",
    "enum": ["EBOM", "MBOM"],
    "description": (
        "EBOM is the engineering view — what the product is. MBOM is the "
        "manufacturing view — what the line consumes to build it, including "
        "consumables, packaging and routing. Defaults to EBOM."
    ),
}

_AS_OF_PROPERTY = {
    "type": "string",
    "description": (
        "ISO date (YYYY-MM-DD). Filters lines by effectivity, so a past date "
        "returns the structure as it stood then. Defaults to today."
    ),
}


register(
    ToolSpec(
        name="get_bom_structure",
        domain="pdm",
        description=(
            "Retrieve the nested bill of materials for a Magnotherm part number, "
            "with every sub-assembly and component, its material type, coating, "
            "revision, quantity, and quantity-per-finished-unit. Use this for any "
            "question about what a product is made of or how it is assembled. "
            "Example part numbers: ECL-SYS-1000 (ECLIPSE 1kW retail chiller), "
            "ECL-AMR-200 (Active Magnetic Regenerator module)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "part_number": {
                    "type": "string",
                    "description": "The part number to expand, e.g. 'ECL-SYS-1000'.",
                },
                "bom_type": _BOM_TYPE_PROPERTY,
                "as_of": _AS_OF_PROPERTY,
            },
            "required": ["part_number"],
            "additionalProperties": False,
        },
        handler=get_bom_structure,
    )
)


register(
    ToolSpec(
        name="get_where_used",
        domain="pdm",
        description=(
            "Find every assembly and finished product that contains a given part, "
            "directly or at any depth. Use this before proposing a change to a "
            "component, to establish what the change would affect, and to answer "
            "'which products use this part?'. Returns the top-level products "
            "separately, because those are the ones a change notice has to name."
        ),
        parameters={
            "type": "object",
            "properties": {
                "part_number": {
                    "type": "string",
                    "description": "The component to trace upward, e.g. 'LFS-POR-010'.",
                },
                "bom_type": _BOM_TYPE_PROPERTY,
                "as_of": _AS_OF_PROPERTY,
            },
            "required": ["part_number"],
            "additionalProperties": False,
        },
        handler=get_where_used,
    )
)


register(
    ToolSpec(
        name="get_compliance_rollup",
        domain="pdm",
        description=(
            "Check whether a product's sustainability and compliance claims hold "
            "across its whole bill of materials: PFAS-free, free of heavy rare "
            "earth elements, RoHS/REACH status, and total direct GWP. Use this "
            "whenever asked to confirm or evidence such a claim. Each verdict is "
            "'proven', 'violated', or 'unproven' — unproven means some component "
            "has never been assessed, which is NOT the same as compliant, and the "
            "unassessed components are listed as gaps."
        ),
        parameters={
            "type": "object",
            "properties": {
                "part_number": {
                    "type": "string",
                    "description": "The product to assess, e.g. 'ECL-SYS-1000'.",
                },
                "bom_type": _BOM_TYPE_PROPERTY,
                "as_of": _AS_OF_PROPERTY,
            },
            "required": ["part_number"],
            "additionalProperties": False,
        },
        handler=get_compliance_rollup,
    )
)


register(
    ToolSpec(
        name="get_part_detail",
        domain="pdm",
        description=(
            "Retrieve one part's master record and its full revision history: "
            "lifecycle state of each revision, when it was released, what change "
            "order created it, plus classification, cost, lead time and whether "
            "it is a tracked configuration item. Use this for questions about a "
            "single part rather than a structure."
        ),
        parameters={
            "type": "object",
            "properties": {
                "part_number": {
                    "type": "string",
                    "description": "The part number, e.g. 'LFS-POR-010'.",
                }
            },
            "required": ["part_number"],
            "additionalProperties": False,
        },
        handler=get_part_detail,
    )
)


register(
    ToolSpec(
        name="diff_baselines",
        domain="pdm",
        description=(
            "Compare two captured configuration baselines and report what was "
            "added, removed and changed between them. Use this to answer 'what "
            "changed between these two configurations?'. Both baselines must be "
            "the same BOM type."
        ),
        parameters={
            "type": "object",
            "properties": {
                "from_baseline": {
                    "type": "string",
                    "description": "Name of the earlier baseline.",
                },
                "to_baseline": {
                    "type": "string",
                    "description": "Name of the later baseline.",
                },
            },
            "required": ["from_baseline", "to_baseline"],
            "additionalProperties": False,
        },
        handler=diff_baselines,
    )
)


# --------------------------------------------------------------------------
# Mutating
# --------------------------------------------------------------------------


async def _preview_derive_mbom(
    session: AsyncSession, part_number: str
) -> ProposalPreview:
    """Run the real derivation, describe it, then throw the writes away.

    The preview is produced by the same function that will perform the change,
    so the reviewer cannot be shown a diff that the applier then fails to
    reproduce. The rollback is what keeps it a preview — and it is why the
    actor here is the system rather than the calling agent: with `commit=False`
    nothing is recorded, so there is no act to attribute.
    """
    result = await derive_mbom(
        session, actor=SYSTEM_PRINCIPAL, part_number=part_number, commit=False
    )
    await session.rollback()

    changes = [
        ProposedChange(
            kind="modify",
            target=f"MBOM {result.root_part_number} rev {result.root_revision}",
            field="line count",
            before=None,
            after=result.edges_after,
        ),
        *(
            ProposedChange(
                kind="add" if delta.delta_type.value == "Add" else "modify",
                target=(
                    f"{delta.child_part_number or delta.parent_part_number or 'root'}"
                ),
                field=delta.delta_type.value,
                after=delta.rationale,
            )
            for delta in result.deltas
        ),
    ]

    return ProposalPreview(
        summary=(
            f"Rebuild the {result.root_part_number} MBOM from EBOM revision "
            f"{result.root_revision}: {result.edges_copied_from_ebom} engineering "
            f"lines copied, {result.deltas_applied} manufacturing deltas applied, "
            f"{result.edges_after} lines in total."
        ),
        entity_type="MBOM",
        entity_ref=f"{result.root_part_number}@{result.root_revision}",
        changes=changes,
        warnings=result.warnings,
    )


async def _apply_derive_mbom(
    session: AsyncSession, *, actor: Principal, part_number: str, **_: object
) -> dict:
    # commit=False: the approval flow owns the transaction, so the derivation,
    # its audit event, and the proposal's status change land together.
    result = await derive_mbom(
        session, actor=actor, part_number=part_number, commit=False
    )
    return result.model_dump(mode="json")


register(
    ToolSpec(
        name="derive_mbom",
        domain="pdm",
        description=(
            "Rebuild the manufacturing bill of materials for a product from its "
            "released engineering BOM plus the stored manufacturing deltas "
            "(consumables, packaging, phantom kits, routing assignments). Use "
            "this after an engineering change, when the MBOM needs to catch up "
            "with the EBOM. This changes production data, so it is prepared for "
            "approval rather than applied directly."
        ),
        parameters={
            "type": "object",
            "properties": {
                "part_number": {
                    "type": "string",
                    "description": "The product to rebuild, e.g. 'ECL-SYS-1000'.",
                }
            },
            "required": ["part_number"],
            "additionalProperties": False,
        },
        handler=_preview_derive_mbom,
        applier=_apply_derive_mbom,
        required_role=Role.MANUFACTURING,
    )
)
