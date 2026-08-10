"""BOM traversal: effectivity, revision resolution, quantities, where-used."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.pdm.models import (
    BomEdge,
    BomType,
    CoatingStatus,
    ComplianceStatus,
    Declaration,
    LifecycleState,
    MaterialType,
    Part,
    PartClass,
    PartRevision,
)
from app.domains.pdm.service import (
    get_bom_structure,
    get_compliance_rollup,
    get_where_used,
)
from app.tools.registry import ToolError

pytestmark = pytest.mark.db

RELEASED = datetime(2025, 1, 1, tzinfo=timezone.utc)


async def make_part(
    session: AsyncSession,
    part_number: str,
    *,
    revision: str = "A",
    state: LifecycleState = LifecycleState.RELEASED,
    part_class: PartClass = PartClass.MECHANICAL,
    pfas_free: Declaration = Declaration.YES,
    gwp: float | None = 0.0,
    released_at: datetime | None = RELEASED,
) -> tuple[Part, PartRevision]:
    part = Part(
        part_number=part_number,
        description=f"{part_number} description",
        material_type=MaterialType.STEEL,
        coating_status=CoatingStatus.UNCOATED,
        part_class=part_class,
        pfas_free=pfas_free,
        contains_heavy_rare_earth=Declaration.NO,
        # Fully declared by default, so a test about one attribute is not
        # muddied by gaps in the two it does not care about.
        rohs_reach_status=ComplianceStatus.COMPLIANT,
        gwp_direct=gwp,
    )
    session.add(part)
    await session.flush()
    rev = PartRevision(
        part_id=part.id,
        revision=revision,
        lifecycle_state=state,
        released_at=released_at if state is LifecycleState.RELEASED else None,
    )
    session.add(rev)
    await session.flush()
    return part, rev


async def link(
    session: AsyncSession,
    parent_rev: PartRevision,
    child: Part,
    *,
    quantity: str = "1",
    find_number: str | None = None,
    bom_type: BomType = BomType.EBOM,
    effective_from: date | None = None,
    effective_to: date | None = None,
    scrap: str = "0",
    child_revision: PartRevision | None = None,
) -> BomEdge:
    edge = BomEdge(
        parent_revision_id=parent_rev.id,
        child_part_id=child.id,
        child_revision_id=child_revision.id if child_revision else None,
        bom_type=bom_type,
        quantity=Decimal(quantity),
        find_number=find_number,
        effective_from=effective_from,
        effective_to=effective_to,
        scrap_factor=Decimal(scrap),
    )
    session.add(edge)
    await session.flush()
    return edge


def flatten(node) -> dict[str, object]:
    """part_number -> node, for trees where each part appears once."""
    out = {}

    def walk(n):
        out[n.part_number] = n
        for c in n.children:
            walk(c)

    walk(node)
    return out


# --------------------------------------------------------------------------
# Effectivity
# --------------------------------------------------------------------------

CHANGE_DAY = date(2025, 6, 1)


@pytest.fixture
async def phased_tree(session: AsyncSession):
    """TOP contains OLD until 2025-06-01, and NEW from that day on."""
    top, top_rev = await make_part(session, "TOP-001", part_class=PartClass.ASSEMBLY)
    old, _ = await make_part(session, "OLD-001")
    new, _ = await make_part(session, "NEW-001")
    await link(session, top_rev, old, quantity="6", find_number="110", effective_to=CHANGE_DAY)
    await link(session, top_rev, new, quantity="8", find_number="111", effective_from=CHANGE_DAY)
    await session.commit()
    return top, old, new


async def test_effectivity_returns_the_old_line_before_the_change(
    session: AsyncSession, phased_tree
) -> None:
    bom = await get_bom_structure(session, "TOP-001", as_of=date(2025, 5, 31))
    nodes = flatten(bom.tree)
    assert "OLD-001" in nodes
    assert "NEW-001" not in nodes
    assert nodes["OLD-001"].quantity == 6


async def test_effectivity_bounds_are_half_open(
    session: AsyncSession, phased_tree
) -> None:
    # On the changeover day itself the new line is in and the old one is out.
    # A closed upper bound would return both and double the bed count.
    bom = await get_bom_structure(session, "TOP-001", as_of=CHANGE_DAY)
    nodes = flatten(bom.tree)
    assert "NEW-001" in nodes
    assert "OLD-001" not in nodes


async def test_effectivity_returns_the_new_line_after_the_change(
    session: AsyncSession, phased_tree
) -> None:
    bom = await get_bom_structure(session, "TOP-001", as_of=date(2026, 1, 1))
    nodes = flatten(bom.tree)
    assert nodes["NEW-001"].quantity == 8
    assert "OLD-001" not in nodes


# --------------------------------------------------------------------------
# Revision resolution
# --------------------------------------------------------------------------


async def test_unpinned_child_resolves_to_the_latest_released_revision(
    session: AsyncSession,
) -> None:
    top, top_rev = await make_part(session, "TOP-002", part_class=PartClass.ASSEMBLY)
    child, rev_a = await make_part(session, "CHD-002", revision="A")
    # A newer released revision, and a newer still one that is only in design.
    session.add(
        PartRevision(
            part_id=child.id,
            revision="B",
            lifecycle_state=LifecycleState.RELEASED,
            released_at=datetime(2025, 8, 1, tzinfo=timezone.utc),
        )
    )
    session.add(
        PartRevision(
            part_id=child.id,
            revision="C",
            lifecycle_state=LifecycleState.IN_DESIGN,
        )
    )
    await link(session, top_rev, child)
    await session.commit()

    bom = await get_bom_structure(session, "TOP-002")
    # B, not C: an unreleased revision is not what the line is built from.
    assert flatten(bom.tree)["CHD-002"].revision == "B"


async def test_a_pinned_child_revision_overrides_the_latest(
    session: AsyncSession,
) -> None:
    top, top_rev = await make_part(session, "TOP-003", part_class=PartClass.ASSEMBLY)
    child, rev_a = await make_part(session, "CHD-003", revision="A")
    session.add(
        PartRevision(
            part_id=child.id,
            revision="B",
            lifecycle_state=LifecycleState.RELEASED,
            released_at=datetime(2025, 8, 1, tzinfo=timezone.utc),
        )
    )
    await link(session, top_rev, child, child_revision=rev_a)
    await session.commit()

    bom = await get_bom_structure(session, "TOP-003")
    assert flatten(bom.tree)["CHD-003"].revision == "A"


async def test_a_part_with_no_revisions_reports_that_rather_than_unknown_part(
    session: AsyncSession,
) -> None:
    part = Part(
        part_number="NOR-001",
        description="No revisions",
        material_type=MaterialType.STEEL,
        coating_status=CoatingStatus.UNCOATED,
    )
    session.add(part)
    await session.commit()

    with pytest.raises(ToolError, match="no revisions"):
        await get_bom_structure(session, "NOR-001")


async def test_unknown_part_lists_the_known_ones(session: AsyncSession) -> None:
    await make_part(session, "KNW-001")
    await session.commit()
    with pytest.raises(ToolError, match="KNW-001"):
        await get_bom_structure(session, "NOPE-000")


# --------------------------------------------------------------------------
# Quantities
# --------------------------------------------------------------------------


async def test_extended_quantity_multiplies_down_the_tree(
    session: AsyncSession,
) -> None:
    top, top_rev = await make_part(session, "TOP-004", part_class=PartClass.ASSEMBLY)
    mid, mid_rev = await make_part(session, "MID-004", part_class=PartClass.ASSEMBLY)
    leaf, _ = await make_part(session, "LEA-004")
    await link(session, top_rev, mid, quantity="3")
    await link(session, mid_rev, leaf, quantity="4")
    await session.commit()

    nodes = flatten((await get_bom_structure(session, "TOP-004")).tree)
    assert nodes["MID-004"].quantity == 3
    assert nodes["LEA-004"].quantity == 4
    # 3 sub-assemblies of 4 each: twelve per finished unit, which is the number
    # procurement needs and the per-line quantity never shows.
    assert nodes["LEA-004"].extended_quantity == 12


async def test_scrap_compounds_through_a_subassembly(session: AsyncSession) -> None:
    top, top_rev = await make_part(session, "TOP-005", part_class=PartClass.ASSEMBLY)
    mid, mid_rev = await make_part(session, "MID-005", part_class=PartClass.ASSEMBLY)
    leaf, _ = await make_part(session, "LEA-005")
    await link(session, top_rev, mid, quantity="2", scrap="0.10")
    await link(session, mid_rev, leaf, quantity="5", scrap="0.20")
    await session.commit()

    nodes = flatten((await get_bom_structure(session, "TOP-005")).tree)
    # 2 x 1.10 = 2.2 sub-assemblies, each needing 5 x 1.20 = 6 leaves.
    assert nodes["MID-005"].extended_quantity == pytest.approx(2.2)
    assert nodes["LEA-005"].extended_quantity == pytest.approx(13.2)


async def test_a_cyclic_bom_terminates(session: AsyncSession) -> None:
    a, a_rev = await make_part(session, "CYC-A", part_class=PartClass.ASSEMBLY)
    b, b_rev = await make_part(session, "CYC-B", part_class=PartClass.ASSEMBLY)
    await link(session, a_rev, b)
    await link(session, b_rev, a)  # the cycle
    await session.commit()

    bom = await get_bom_structure(session, "CYC-A")
    # The guard stops at the repeat rather than recursing to the depth ceiling.
    assert bom.total_nodes == 2
    assert bom.max_depth == 1


# --------------------------------------------------------------------------
# Where-used
# --------------------------------------------------------------------------


@pytest.fixture
async def shared_child(session: AsyncSession):
    """A seal used by two different sub-assemblies of one product."""
    top, top_rev = await make_part(session, "PRD-100", part_class=PartClass.ASSEMBLY)
    left, left_rev = await make_part(session, "SUB-101", part_class=PartClass.ASSEMBLY)
    right, right_rev = await make_part(session, "SUB-102", part_class=PartClass.ASSEMBLY)
    seal, _ = await make_part(session, "SEA-999")
    await link(session, top_rev, left, find_number="100")
    await link(session, top_rev, right, find_number="200")
    await link(session, left_rev, seal, quantity="4", find_number="110")
    await link(session, right_rev, seal, quantity="2", find_number="210")
    await session.commit()
    return top, seal


async def test_where_used_finds_every_parent_at_every_depth(
    session: AsyncSession, shared_child
) -> None:
    result = await get_where_used(session, "SEA-999")
    parents = {row.part_number for row in result.rows}
    assert parents == {"SUB-101", "SUB-102", "PRD-100"}
    assert result.total_parents == 3


async def test_where_used_names_the_top_level_product_once(
    session: AsyncSession, shared_child
) -> None:
    result = await get_where_used(session, "SEA-999")
    # Reached by two paths, but a change notice names the product once.
    assert result.top_level_products == ["PRD-100"]
    assert sum(1 for row in result.rows if row.part_number == "PRD-100") == 2


async def test_where_used_reports_the_quantity_on_each_parent(
    session: AsyncSession, shared_child
) -> None:
    result = await get_where_used(session, "SEA-999")
    by_parent = {row.part_number: row.quantity for row in result.rows if row.depth == 1}
    assert by_parent == {"SUB-101": 4, "SUB-102": 2}


async def test_where_used_is_empty_for_a_part_nothing_contains(
    session: AsyncSession, shared_child
) -> None:
    result = await get_where_used(session, "PRD-100")
    assert result.rows == []
    assert result.top_level_products == []


async def test_where_used_ignores_lines_that_have_phased_out(
    session: AsyncSession, phased_tree
) -> None:
    result = await get_where_used(session, "OLD-001", as_of=date(2026, 1, 1))
    assert result.rows == []


# --------------------------------------------------------------------------
# Compliance
# --------------------------------------------------------------------------


async def test_a_fully_declared_product_is_proven(session: AsyncSession) -> None:
    top, top_rev = await make_part(session, "CMP-001", part_class=PartClass.ASSEMBLY)
    child, _ = await make_part(session, "CMP-002", pfas_free=Declaration.YES, gwp=0.0)
    await link(session, top_rev, child)
    await session.commit()

    rollup = await get_compliance_rollup(session, "CMP-001")
    assert rollup.pfas_free == "proven"
    assert rollup.gaps == []
    assert rollup.total_direct_gwp == 0.0


async def test_an_unassessed_component_makes_the_claim_unproven_not_true(
    session: AsyncSession,
) -> None:
    top, top_rev = await make_part(session, "CMP-010", part_class=PartClass.ASSEMBLY)
    good, _ = await make_part(session, "CMP-011", pfas_free=Declaration.YES)
    unknown, _ = await make_part(
        session, "CMP-012", pfas_free=Declaration.UNKNOWN, gwp=None
    )
    await link(session, top_rev, good)
    await link(session, top_rev, unknown)
    await session.commit()

    rollup = await get_compliance_rollup(session, "CMP-010")
    assert rollup.pfas_free == "unproven"
    assert {gap.part_number for gap in rollup.gaps} == {"CMP-012"}
    # A partial total would be quoted as if it were the whole figure.
    assert rollup.total_direct_gwp is None


async def test_a_contradicting_component_makes_the_claim_violated(
    session: AsyncSession,
) -> None:
    top, top_rev = await make_part(session, "CMP-020", part_class=PartClass.ASSEMBLY)
    bad, _ = await make_part(session, "CMP-021", pfas_free=Declaration.NO)
    await link(session, top_rev, bad)
    await session.commit()

    rollup = await get_compliance_rollup(session, "CMP-020")
    assert rollup.pfas_free == "violated"
    assert {v.part_number for v in rollup.violations} == {"CMP-021"}


async def test_a_shared_component_is_judged_once_but_counted_at_each_position(
    session: AsyncSession, shared_child
) -> None:
    top, seal = shared_child
    seal.pfas_free = Declaration.UNKNOWN
    seal.gwp_direct = None
    await session.commit()

    rollup = await get_compliance_rollup(session, "PRD-100")
    # One PFAS gap, not two, even though the seal sits at two positions.
    pfas_gaps = [gap for gap in rollup.gaps if gap.attribute == "pfas_free"]
    assert [gap.part_number for gap in pfas_gaps] == ["SEA-999"]
