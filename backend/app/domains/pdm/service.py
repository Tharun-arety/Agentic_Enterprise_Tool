"""PDM read services. The tool layer and the REST layer both call these."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.pdm.models import (
    BomType,
    ComplianceStatus,
    Declaration,
    Part,
    PartClass,
    PartRevision,
)
from app.domains.pdm.queries import BOM_EXPLODE, MAX_BOM_DEPTH, WHERE_USED
from app.domains.pdm.schemas import (
    BomNode,
    BomResponse,
    ComplianceGap,
    ComplianceRollup,
    PartDetail,
    WhereUsedResponse,
    WhereUsedRow,
)
from app.tools.registry import ToolError

logger = logging.getLogger(__name__)

# Part classes that carry no material of their own: an assembly is the sum of
# its children, a phantom is a kitting convenience, a document is paperwork.
# Rolling a compliance claim over them would double-count at best and, more
# often, report an unassessed container as an unassessed component.
_NON_MATERIAL_CLASSES = {PartClass.ASSEMBLY, PartClass.PHANTOM, PartClass.DOCUMENT}


def _today() -> date:
    return datetime.now(timezone.utc).date()


async def _resolve_part(session: AsyncSession, part_number: str) -> Part:
    """Look up a part, failing with a message that lists the alternatives."""
    part = (
        await session.execute(select(Part).where(Part.part_number == part_number))
    ).scalar_one_or_none()
    if part is not None:
        return part

    known = (
        await session.execute(select(Part.part_number).order_by(Part.part_number))
    ).scalars().all()
    raise ToolError(
        f"No part named {part_number!r}. Known part numbers: {', '.join(known)}"
        if known
        else f"No part named {part_number!r} and the parts table is empty — "
        "has the database been seeded?"
    )


# --------------------------------------------------------------------------
# Explode
# --------------------------------------------------------------------------


async def get_bom_structure(
    session: AsyncSession,
    part_number: str,
    bom_type: str = BomType.EBOM.value,
    as_of: date | None = None,
    max_depth: int = MAX_BOM_DEPTH,
) -> BomResponse:
    """Return the nested bill of materials beneath `part_number`.

    `bom_type` selects the engineering ("EBOM") or manufacturing ("MBOM") view.
    `as_of` filters edge effectivity, so asking for a past date returns the
    structure as it stood then rather than as it stands now.
    """
    part_number = part_number.strip().upper()
    effective_date = as_of or _today()
    try:
        view = BomType(bom_type.strip().upper())
    except ValueError:
        raise ToolError(
            f"Unknown BOM type {bom_type!r}. Use 'EBOM' for the engineering view "
            "or 'MBOM' for the manufacturing view."
        ) from None

    # Called for its refusal, not its return: it raises with the list of known
    # part numbers, which distinguishes a typo from a part that exists but has
    # no revision to explode.
    await _resolve_part(session, part_number)

    rows = (
        await session.execute(
            BOM_EXPLODE,
            {
                "part_number": part_number,
                "bom_type": view.value,
                "as_of": effective_date,
                "max_depth": max_depth,
                "root_revision_id": None,
            },
        )
    ).mappings().all()

    if not rows:
        # The part exists, so the empty result means it has no revision to
        # explode from. Saying "unknown part" here would send someone hunting
        # for a typo that is not there.
        raise ToolError(
            f"{part_number} has no revisions, so there is nothing to explode. "
            "Create an initial revision first."
        )

    nodes: dict[tuple[str, ...], BomNode] = {}
    root: BomNode | None = None

    for row in rows:
        node = BomNode(
            part_number=row["part_number"],
            description=row["description"],
            material_type=row["material_type"],
            coating_status=row["coating_status"],
            part_class=row["part_class"],
            revision=row["revision"],
            lifecycle_state=row["lifecycle_state"],
            quantity=float(row["quantity"]),
            extended_quantity=float(row["extended_quantity"]),
            unit_of_measure=row["unit_of_measure"],
            find_number=row["find_number"],
            reference_designator=row["reference_designator"],
            operation_seq=row["operation_seq"],
            is_phantom=row["is_phantom"],
            scrap_factor=float(row["scrap_factor"]),
            is_configuration_item=row["is_configuration_item"],
            pfas_free=row["pfas_free"],
            contains_heavy_rare_earth=row["contains_heavy_rare_earth"],
            rohs_reach_status=row["rohs_reach_status"],
            gwp_direct=row["gwp_direct"],
            standard_cost=(
                float(row["standard_cost"]) if row["standard_cost"] is not None else None
            ),
            depth=row["depth"],
            children=[],
        )
        # Keyed by the full path rather than the part id, because a shared
        # component legitimately appears at several points in one tree.
        key = tuple(row["path"])
        nodes[key] = node
        if len(key) == 1:
            root = node
        else:
            parent = nodes.get(key[:-1])
            if parent is None:  # pragma: no cover - ordering makes this unreachable
                logger.warning("Orphan BOM row for %s; skipping.", node.part_number)
                continue
            parent.children.append(node)

    assert root is not None  # guaranteed: rows is non-empty and depth 0 sorts first
    return BomResponse(
        root_part_number=root.part_number,
        root_revision=root.revision,
        bom_type=view,
        as_of=effective_date,
        total_nodes=len(nodes),
        max_depth=max(row["depth"] for row in rows),
        tree=root,
    )


# --------------------------------------------------------------------------
# Where-used
# --------------------------------------------------------------------------


async def get_where_used(
    session: AsyncSession,
    part_number: str,
    bom_type: str = BomType.EBOM.value,
    as_of: date | None = None,
    max_depth: int = MAX_BOM_DEPTH,
) -> WhereUsedResponse:
    """Every assembly that contains `part_number`, directly or indirectly.

    This is the first question an engineering change has to answer: altering a
    component is only safe once you know everything it is inside.
    """
    part_number = part_number.strip().upper()
    effective_date = as_of or _today()
    try:
        view = BomType(bom_type.strip().upper())
    except ValueError:
        raise ToolError(f"Unknown BOM type {bom_type!r}. Use 'EBOM' or 'MBOM'.") from None

    await _resolve_part(session, part_number)

    rows = (
        await session.execute(
            WHERE_USED,
            {
                "part_number": part_number,
                "bom_type": view.value,
                "as_of": effective_date,
                "max_depth": max_depth,
            },
        )
    ).mappings().all()

    parents = [
        WhereUsedRow(
            part_number=row["part_number"],
            description=row["description"],
            part_class=row["part_class"],
            revision=row["revision"],
            lifecycle_state=row["lifecycle_state"],
            is_configuration_item=row["is_configuration_item"],
            quantity=float(row["quantity"]),
            depth=row["depth"],
            via_part_number=row["via_part_number"],
            is_top_level=row["is_top_level"],
        )
        for row in rows
    ]

    # Deduplicated and ordered: the same product can be reached by more than
    # one path, and a change notice should name it once.
    top_level = sorted({row.part_number for row in parents if row.is_top_level})

    return WhereUsedResponse(
        part_number=part_number,
        bom_type=view,
        as_of=effective_date,
        total_parents=len({row.part_number for row in parents}),
        top_level_products=top_level,
        rows=parents,
    )


# --------------------------------------------------------------------------
# Compliance rollup
# --------------------------------------------------------------------------


def _verdict(
    nodes: list[BomNode],
    attribute: str,
    *,
    good: Declaration,
    bad: Declaration,
) -> tuple[str, list[ComplianceGap], list[ComplianceGap]]:
    """Reduce a per-component declaration to one claim about the product."""
    gaps: list[ComplianceGap] = []
    violations: list[ComplianceGap] = []

    for node in nodes:
        value: Declaration = getattr(node, attribute)
        if value is bad:
            violations.append(
                ComplianceGap(
                    part_number=node.part_number,
                    description=node.description,
                    attribute=attribute,
                    value=value.value,
                )
            )
        elif value is not good:
            gaps.append(
                ComplianceGap(
                    part_number=node.part_number,
                    description=node.description,
                    attribute=attribute,
                    value=value.value,
                )
            )

    if violations:
        return "violated", gaps, violations
    if gaps:
        return "unproven", gaps, violations
    return "proven", gaps, violations


async def get_compliance_rollup(
    session: AsyncSession,
    part_number: str,
    bom_type: str = BomType.EBOM.value,
    as_of: date | None = None,
) -> ComplianceRollup:
    """Whether a product's sustainability claims hold across its whole BOM.

    Returns three-valued verdicts. An unassessed component makes a claim
    *unproven*, never compliant — the difference is what stands between an
    evidenced statement to a customer and a guess.
    """
    bom = await get_bom_structure(session, part_number, bom_type=bom_type, as_of=as_of)

    # Two different collections, because the two questions differ. A shared
    # component occupies several positions in the tree but is one part: its
    # PFAS declaration should be judged once, while its contribution to a
    # total has to be counted at every position it occupies.
    positions: list[BomNode] = []

    def walk(node: BomNode) -> None:
        if node.part_class not in _NON_MATERIAL_CLASSES:
            positions.append(node)
        for child in node.children:
            walk(child)

    walk(bom.tree)

    flat: list[BomNode] = list(
        {node.part_number: node for node in positions}.values()
    )

    pfas, pfas_gaps, pfas_violations = _verdict(
        flat, "pfas_free", good=Declaration.YES, bad=Declaration.NO
    )
    # Inverted: for heavy rare earths the good answer is "no". Excluding them
    # is what keeps the magnet supply outside the scope of export restrictions.
    hree, hree_gaps, hree_violations = _verdict(
        flat, "contains_heavy_rare_earth", good=Declaration.NO, bad=Declaration.YES
    )

    rohs_gaps = [
        ComplianceGap(
            part_number=node.part_number,
            description=node.description,
            attribute="rohs_reach_status",
            value=node.rohs_reach_status.value,
        )
        for node in flat
        if node.rohs_reach_status is ComplianceStatus.UNKNOWN
    ]
    rohs_violations = [
        ComplianceGap(
            part_number=node.part_number,
            description=node.description,
            attribute="rohs_reach_status",
            value=node.rohs_reach_status.value,
        )
        for node in flat
        if node.rohs_reach_status is ComplianceStatus.NON_COMPLIANT
    ]
    rohs = (
        "violated" if rohs_violations else "unproven" if rohs_gaps else "proven"
    )

    # Summed only when every component carries a figure. A partial total
    # understates the product and invites being quoted as though it were
    # complete, so a single missing value collapses it to None and records the
    # component that is missing.
    unmeasured = [node for node in flat if node.gwp_direct is None]
    total_gwp: float | None = None
    if not unmeasured:
        total_gwp = round(
            sum(node.extended_quantity * (node.gwp_direct or 0.0) for node in positions),
            6,
        )
    gwp_gaps = [
        ComplianceGap(
            part_number=node.part_number,
            description=node.description,
            attribute="gwp_direct",
            value="not assessed",
        )
        for node in unmeasured
    ]

    return ComplianceRollup(
        root_part_number=bom.root_part_number,
        bom_type=bom.bom_type,
        as_of=bom.as_of,
        components_assessed=len(flat),
        pfas_free=pfas,
        heavy_rare_earth_free=hree,
        rohs_reach=rohs,
        total_direct_gwp=total_gwp,
        gaps=pfas_gaps + hree_gaps + rohs_gaps + gwp_gaps,
        violations=pfas_violations + hree_violations + rohs_violations,
    )


# --------------------------------------------------------------------------
# Part master
# --------------------------------------------------------------------------


async def get_part_detail(session: AsyncSession, part_number: str) -> PartDetail:
    """A part with its full revision history."""
    part_number = part_number.strip().upper()
    part = (
        await session.execute(
            select(Part)
            .where(Part.part_number == part_number)
            .options(selectinload(Part.revisions))
        )
    ).scalar_one_or_none()
    if part is None:
        await _resolve_part(session, part_number)  # raises with the known list
    return PartDetail.model_validate(part)


async def latest_revision(session: AsyncSession, part: Part) -> PartRevision | None:
    """The revision a BOM edge means when it does not pin one.

    Mirrors the `effective_rev` CTE in queries.py: most recently released,
    falling back to the newest revision of any state.
    """
    revisions = (
        await session.execute(
            select(PartRevision).where(PartRevision.part_id == part.id)
        )
    ).scalars().all()
    if not revisions:
        return None
    return sorted(
        revisions,
        key=lambda rev: (
            rev.is_released,
            rev.released_at or datetime.min.replace(tzinfo=timezone.utc),
            rev.created_at,
        ),
        reverse=True,
    )[0]
