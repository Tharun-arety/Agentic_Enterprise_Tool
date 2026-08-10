"""MBOM derivation, configuration baselines, and the document vault."""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.filestore import LocalFileStore, content_key
from app.core.principal import SYSTEM_PRINCIPAL
from app.domains.pdm import documents as vault
from app.domains.pdm.baselines import capture_baseline, diff_baselines
from app.domains.pdm.documents import next_revision
from app.domains.pdm.mbom import derive_mbom
from app.domains.pdm.models import (
    BomEdge,
    BomType,
    DocumentKind,
    MbomDelta,
    MbomDeltaType,
    PartClass,
)
from app.domains.pdm.service import get_bom_structure
from app.tools.registry import ToolError
from tests.test_pdm_structure import flatten, link, make_part

pytestmark = pytest.mark.db


@pytest.fixture
async def product(session: AsyncSession):
    """A two-level product: TOP -> SUB -> {WIDGET, FLUID}."""
    top, top_rev = await make_part(session, "MB-TOP", part_class=PartClass.ASSEMBLY)
    sub, sub_rev = await make_part(session, "MB-SUB", part_class=PartClass.ASSEMBLY)
    widget, _ = await make_part(session, "MB-WID")
    fluid, _ = await make_part(session, "MB-FLD", part_class=PartClass.CONSUMABLE)
    crate, _ = await make_part(session, "MB-PKG", part_class=PartClass.PACKAGING)
    await link(session, top_rev, sub, quantity="1", find_number="100")
    await link(session, sub_rev, widget, quantity="2", find_number="110")
    await link(session, sub_rev, fluid, quantity="1", find_number="120")
    await session.commit()
    return {"top": top, "top_rev": top_rev, "sub": sub, "fluid": fluid, "crate": crate}


async def add_delta(session: AsyncSession, root_rev, **kwargs) -> MbomDelta:
    delta = MbomDelta(root_revision_id=root_rev.id, **kwargs)
    session.add(delta)
    await session.commit()
    return delta


# --------------------------------------------------------------------------
# Derivation
# --------------------------------------------------------------------------


async def test_derivation_copies_the_engineering_structure(
    session: AsyncSession, product
) -> None:
    result = await derive_mbom(
        session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", commit=True
    )
    assert result.edges_copied_from_ebom == 3
    assert result.edges_after == 3

    mbom = flatten((await get_bom_structure(session, "MB-TOP", bom_type="MBOM")).tree)
    assert set(mbom) == {"MB-TOP", "MB-SUB", "MB-WID", "MB-FLD"}


async def test_derivation_is_idempotent(session: AsyncSession, product) -> None:
    first = await derive_mbom(
        session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", commit=True
    )
    second = await derive_mbom(
        session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", commit=True
    )
    # Rebuilding must clear the previous derivation, not layer onto it.
    assert first.edges_after == second.edges_after == 3


async def test_an_add_delta_introduces_a_line_the_ebom_does_not_have(
    session: AsyncSession, product
) -> None:
    await add_delta(
        session,
        product["top_rev"],
        sequence=10,
        delta_type=MbomDeltaType.ADD,
        child_part_id=product["crate"].id,
        quantity=Decimal("1"),
        unit_of_measure="ea",
        operation_seq=40,
        rationale="Export crate; shipping configuration, not product function.",
    )
    result = await derive_mbom(
        session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", commit=True
    )
    assert result.deltas_applied == 1
    assert result.edges_after == 4

    ebom = flatten((await get_bom_structure(session, "MB-TOP")).tree)
    mbom = flatten((await get_bom_structure(session, "MB-TOP", bom_type="MBOM")).tree)
    assert "MB-PKG" not in ebom, "packaging must not leak into the design view"
    assert mbom["MB-PKG"].operation_seq == 40


async def test_a_requantify_delta_changes_quantity_and_unit(
    session: AsyncSession, product
) -> None:
    await add_delta(
        session,
        product["top_rev"],
        sequence=10,
        delta_type=MbomDeltaType.REQUANTIFY,
        parent_part_id=product["sub"].id,
        child_part_id=product["fluid"].id,
        quantity=Decimal("1.8"),
        unit_of_measure="L",
        rationale="Final charge volume including purge losses.",
    )
    await derive_mbom(session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", commit=True)

    ebom = flatten((await get_bom_structure(session, "MB-TOP")).tree)
    mbom = flatten((await get_bom_structure(session, "MB-TOP", bom_type="MBOM")).tree)
    assert ebom["MB-FLD"].quantity == 1
    assert mbom["MB-FLD"].quantity == pytest.approx(1.8)
    assert mbom["MB-FLD"].unit_of_measure == "L"


async def test_a_remove_delta_drops_a_line(session: AsyncSession, product) -> None:
    await add_delta(
        session,
        product["top_rev"],
        sequence=10,
        delta_type=MbomDeltaType.REMOVE,
        parent_part_id=product["sub"].id,
        child_part_id=product["fluid"].id,
        rationale="Filled at the customer site, not on the line.",
    )
    await derive_mbom(session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", commit=True)

    mbom = flatten((await get_bom_structure(session, "MB-TOP", bom_type="MBOM")).tree)
    assert "MB-FLD" not in mbom
    assert "MB-FLD" in flatten((await get_bom_structure(session, "MB-TOP")).tree)


async def test_a_stale_delta_warns_instead_of_failing_the_rebuild(
    session: AsyncSession, product
) -> None:
    orphan, _ = await make_part(session, "MB-GONE")
    await session.commit()
    await add_delta(
        session,
        product["top_rev"],
        sequence=10,
        delta_type=MbomDeltaType.REQUANTIFY,
        parent_part_id=product["sub"].id,
        child_part_id=orphan.id,
        quantity=Decimal("5"),
        rationale="Targets a line the EBOM no longer has.",
    )
    result = await derive_mbom(
        session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", commit=True
    )
    # The planner needs to know which instruction went stale, not to have the
    # whole rebuild collapse.
    assert result.deltas_applied == 0
    assert any("no matching MBOM line" in warning for warning in result.warnings)
    assert result.edges_after == 3


async def test_rederivation_picks_up_a_change_to_the_engineering_bom(
    session: AsyncSession, product
) -> None:
    await derive_mbom(session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", commit=True)

    # Engineering adds a component after the MBOM was last built.
    extra, _ = await make_part(session, "MB-NEW")
    sub_rev = (
        await session.execute(
            select(BomEdge).where(BomEdge.find_number == "110", BomEdge.bom_type == BomType.EBOM)
        )
    ).scalars().first()
    await link(
        session,
        await session.get(type(product["top_rev"]), sub_rev.parent_revision_id),
        extra,
        quantity="3",
        find_number="130",
    )
    await session.commit()

    result = await derive_mbom(
        session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", commit=True
    )
    assert result.edges_copied_from_ebom == 4
    mbom = flatten((await get_bom_structure(session, "MB-TOP", bom_type="MBOM")).tree)
    assert mbom["MB-NEW"].quantity == 3


async def test_derive_mbom_as_a_tool_prepares_a_proposal_without_writing(
    session: AsyncSession, product, user_factory
) -> None:
    """The real mutating tool, end to end through the approval spine.

    Its preview works by running the derivation and rolling back, so this is
    the case where "the preview must not write" is easiest to get wrong.
    """
    import uuid as _uuid

    from app.core.principal import agent_principal
    from app.core.proposals import ProposalStatus, decide
    from app.domains.identity.models import Role
    from app.tools.registry import run_tool
    from tests.conftest import principal_for

    result = await run_tool(
        session,
        "derive_mbom",
        {"part_number": "MB-TOP"},
        actor=agent_principal("PDM Agent"),
    )
    assert result["status"] == "awaiting_approval"
    assert result["required_role"] == Role.MANUFACTURING.value

    # Nothing derived yet: the preview ran the real code and threw it away.
    mbom_lines = (
        await session.execute(
            select(BomEdge).where(BomEdge.bom_type == BomType.MBOM)
        )
    ).scalars().all()
    assert mbom_lines == []

    planner = principal_for(await user_factory(Role.MANUFACTURING))
    decided = await decide(
        session,
        proposal_id=_uuid.UUID(result["proposal_id"]),
        reviewer=planner,
        approve=True,
    )
    assert decided.status is ProposalStatus.APPLIED

    mbom = flatten((await get_bom_structure(session, "MB-TOP", bom_type="MBOM")).tree)
    assert set(mbom) == {"MB-TOP", "MB-SUB", "MB-WID", "MB-FLD"}


async def test_an_engineer_cannot_approve_a_manufacturing_change(
    session: AsyncSession, product, user_factory
) -> None:
    import uuid as _uuid

    from app.core.principal import agent_principal
    from app.core.proposals import ProposalError, decide
    from app.domains.identity.models import Role
    from app.tools.registry import run_tool
    from tests.conftest import principal_for

    result = await run_tool(
        session,
        "derive_mbom",
        {"part_number": "MB-TOP"},
        actor=agent_principal("PDM Agent"),
    )
    engineer = principal_for(await user_factory(Role.ENGINEER))
    with pytest.raises(ProposalError, match="manufacturing"):
        await decide(
            session,
            proposal_id=_uuid.UUID(result["proposal_id"]),
            reviewer=engineer,
            approve=True,
        )


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------


async def test_a_baseline_does_not_move_when_the_data_does(
    session: AsyncSession, product
) -> None:
    await capture_baseline(
        session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", name="before"
    )

    extra, _ = await make_part(session, "MB-LATE")
    await link(session, product["top_rev"], extra, quantity="1", find_number="900")
    await session.commit()

    await capture_baseline(
        session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", name="after"
    )
    diff = await diff_baselines(session, "before", "after")

    # If the snapshot were recomputed on read, both would show the new line and
    # the diff would be empty — which is the failure this design exists to
    # prevent.
    assert [row.part_number for row in diff.added] == ["MB-LATE"]
    assert diff.removed == []


async def test_the_diff_reports_a_changed_quantity(
    session: AsyncSession, product
) -> None:
    await capture_baseline(
        session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", name="qty-before"
    )
    edge = (
        await session.execute(select(BomEdge).where(BomEdge.find_number == "110"))
    ).scalar_one()
    edge.quantity = Decimal("7")
    await session.commit()
    await capture_baseline(
        session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", name="qty-after"
    )

    diff = await diff_baselines(session, "qty-before", "qty-after")
    changed = [row for row in diff.changed if row.field == "quantity"]
    assert len(changed) == 1
    assert changed[0].part_number == "MB-WID"
    assert (changed[0].before, changed[0].after) == ("2", "7")


async def test_the_diff_keys_on_path_so_a_shared_part_is_not_collapsed(
    session: AsyncSession,
) -> None:
    top, top_rev = await make_part(session, "SH-TOP", part_class=PartClass.ASSEMBLY)
    left, left_rev = await make_part(session, "SH-L", part_class=PartClass.ASSEMBLY)
    right, right_rev = await make_part(session, "SH-R", part_class=PartClass.ASSEMBLY)
    seal, _ = await make_part(session, "SH-SEAL")
    await link(session, top_rev, left, find_number="100")
    await link(session, top_rev, right, find_number="200")
    left_edge = await link(session, left_rev, seal, quantity="4", find_number="110")
    await link(session, right_rev, seal, quantity="2", find_number="210")
    await session.commit()

    await capture_baseline(
        session, actor=SYSTEM_PRINCIPAL, part_number="SH-TOP", name="sh-before"
    )
    left_edge.quantity = Decimal("6")
    await session.commit()
    await capture_baseline(
        session, actor=SYSTEM_PRINCIPAL, part_number="SH-TOP", name="sh-after"
    )

    diff = await diff_baselines(session, "sh-before", "sh-after")
    changed = [row for row in diff.changed if row.field == "quantity"]
    # Only the left-hand occurrence moved. Keying on part number would either
    # report both or neither.
    assert len(changed) == 1
    assert changed[0].path == "SH-TOP / SH-L / SH-SEAL"


async def test_baseline_names_are_unique(session: AsyncSession, product) -> None:
    await capture_baseline(
        session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", name="only-once"
    )
    with pytest.raises(ToolError, match="already exists"):
        await capture_baseline(
            session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", name="only-once"
        )


async def test_comparing_an_ebom_baseline_against_an_mbom_one_is_refused(
    session: AsyncSession, product
) -> None:
    await derive_mbom(session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", commit=True)
    await capture_baseline(
        session, actor=SYSTEM_PRINCIPAL, part_number="MB-TOP", name="as-designed"
    )
    await capture_baseline(
        session,
        actor=SYSTEM_PRINCIPAL,
        part_number="MB-TOP",
        name="as-built",
        bom_type=BomType.MBOM.value,
    )
    with pytest.raises(ToolError, match="manufacturing view"):
        await diff_baselines(session, "as-designed", "as-built")


# --------------------------------------------------------------------------
# Document vault
# --------------------------------------------------------------------------


@pytest.fixture
def local_vault(monkeypatch):
    """Point the vault at a scratch directory for the duration of a test.

    Deliberately not pytest's `tmp_path`: its base directory lives under the
    user's TEMP and is not reliably writable on this platform. A directory
    beside the code is, and it is removed either way.
    """
    root = Path(__file__).resolve().parent.parent / "var" / f"test-vault-{uuid4().hex}"
    store = LocalFileStore(root)
    monkeypatch.setattr("app.domains.pdm.documents.get_file_store", lambda: store)
    try:
        yield store
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_revision_letters_skip_the_ambiguous_ones() -> None:
    assert next_revision(None) == "A"
    assert next_revision("A") == "B"
    # I, O and Q are skipped: on a scanned drawing they read as 1, 0 and O.
    assert next_revision("H") == "J"
    assert next_revision("N") == "P"
    assert next_revision("P") == "R"
    assert next_revision("Z") == "ZA"


async def test_check_in_stores_content_and_records_its_hash(
    session: AsyncSession, product, local_vault, user_factory
) -> None:
    from app.domains.identity.models import Role
    from tests.conftest import principal_for

    engineer = principal_for(await user_factory(Role.ENGINEER))
    await vault.create_document(
        session,
        actor=engineer,
        document_number="DOC-001",
        title="Assembly drawing",
        kind=DocumentKind.DRAWING,
        related_part_number="MB-SUB",
    )
    payload = b"<svg>drawing</svg>"
    out = await vault.check_in(
        session,
        actor=engineer,
        document_number="DOC-001",
        filename="DOC-001.svg",
        data=payload,
        content_type="image/svg+xml",
    )

    assert [rev.revision for rev in out.revisions] == ["A"]
    digest, _ = content_key(payload, "DOC-001.svg")
    assert out.revisions[0].content_hash == digest

    chosen, data = await vault.fetch_content(session, document_number="DOC-001")
    assert data == payload
    assert chosen.revision == "A"


async def test_a_second_check_in_becomes_the_next_revision(
    session: AsyncSession, product, local_vault, user_factory
) -> None:
    from app.domains.identity.models import Role
    from tests.conftest import principal_for

    engineer = principal_for(await user_factory(Role.ENGINEER))
    await vault.create_document(
        session,
        actor=engineer,
        document_number="DOC-002",
        title="Work instruction",
        kind=DocumentKind.WORK_INSTRUCTION,
    )
    await vault.check_in(
        session, actor=engineer, document_number="DOC-002", filename="a.txt", data=b"one"
    )
    out = await vault.check_in(
        session, actor=engineer, document_number="DOC-002", filename="a.txt", data=b"two"
    )
    assert [rev.revision for rev in out.revisions] == ["A", "B"]


async def test_re_uploading_identical_content_is_refused(
    session: AsyncSession, product, local_vault, user_factory
) -> None:
    from app.domains.identity.models import Role
    from tests.conftest import principal_for

    engineer = principal_for(await user_factory(Role.ENGINEER))
    await vault.create_document(
        session,
        actor=engineer,
        document_number="DOC-003",
        title="Spec",
        kind=DocumentKind.SPECIFICATION,
    )
    await vault.check_in(
        session, actor=engineer, document_number="DOC-003", filename="s.txt", data=b"same"
    )
    with pytest.raises(ToolError, match="byte-identical"):
        await vault.check_in(
            session,
            actor=engineer,
            document_number="DOC-003",
            filename="s.txt",
            data=b"same",
        )


async def test_a_second_person_cannot_check_in_over_a_held_lock(
    session: AsyncSession, product, local_vault, user_factory
) -> None:
    from app.domains.identity.models import Role
    from tests.conftest import principal_for

    first = principal_for(await user_factory(Role.ENGINEER))
    second = principal_for(await user_factory(Role.ENGINEER))
    await vault.create_document(
        session,
        actor=first,
        document_number="DOC-004",
        title="CAD",
        kind=DocumentKind.CAD_MODEL,
    )
    await vault.check_out(session, actor=first, document_number="DOC-004")

    with pytest.raises(ToolError, match="checked out"):
        await vault.check_out(session, actor=second, document_number="DOC-004")
    with pytest.raises(ToolError, match="cannot check in"):
        await vault.check_in(
            session,
            actor=second,
            document_number="DOC-004",
            filename="x.stp",
            data=b"geometry",
        )


async def test_checking_in_releases_the_lock(
    session: AsyncSession, product, local_vault, user_factory
) -> None:
    from app.domains.identity.models import Role
    from tests.conftest import principal_for

    first = principal_for(await user_factory(Role.ENGINEER))
    second = principal_for(await user_factory(Role.ENGINEER))
    await vault.create_document(
        session,
        actor=first,
        document_number="DOC-005",
        title="CAD",
        kind=DocumentKind.CAD_MODEL,
    )
    await vault.check_out(session, actor=first, document_number="DOC-005")
    out = await vault.check_in(
        session,
        actor=first,
        document_number="DOC-005",
        filename="x.stp",
        data=b"geometry",
    )
    assert out.locked_by is None
    # Now the next person can take it.
    await vault.check_out(session, actor=second, document_number="DOC-005")


async def test_corrupted_stored_content_is_refused_rather_than_served(
    session: AsyncSession, product, local_vault, user_factory
) -> None:
    from app.domains.identity.models import Role
    from tests.conftest import principal_for

    engineer = principal_for(await user_factory(Role.ENGINEER))
    await vault.create_document(
        session,
        actor=engineer,
        document_number="DOC-006",
        title="Certificate",
        kind=DocumentKind.CERTIFICATE,
    )
    await vault.check_in(
        session,
        actor=engineer,
        document_number="DOC-006",
        filename="c.txt",
        data=b"approved content",
    )

    # Corrupt the stored object behind the vault's back.
    chosen, _ = await vault.fetch_content(session, document_number="DOC-006")
    path = local_vault._path(chosen.storage_key)
    path.write_bytes(b"tampered content")

    with pytest.raises(ToolError, match="integrity check"):
        await vault.fetch_content(session, document_number="DOC-006")


def test_a_key_that_escapes_the_vault_is_refused(local_vault) -> None:
    from app.core.filestore import FileStoreError

    # A storage key is data. One crafted with `..` must not be able to read or
    # write outside the vault directory.
    with pytest.raises(FileStoreError, match="escapes the vault"):
        local_vault._path("../../etc/passwd")
