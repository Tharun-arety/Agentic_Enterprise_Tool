"""pdm depth: revisions, bom edges, mbom, baselines, documents

Revision ID: 0002_pdm_depth
Revises: 0001_baseline
Created: 2026-08-09

Structural, and it carries data across rather than dropping it:

*   `parts.revision` (one mutable string) becomes `part_revisions` (a row per
    issued revision). Each existing part gets one released revision holding
    whatever its string said.
*   `assemblies` (part -> part) becomes `bom_edges` (part *revision* -> part,
    typed EBOM or MBOM). Each existing edge is rehomed onto the backfilled
    revision of its parent.

Order matters. The new tables and the backfill both have to be in place before
the old ones are dropped, so this does not follow the order autogenerate
produced.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_pdm_depth"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(*values: str, name: str, length: int) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=length)


def upgrade() -> None:
    # ----------------------------------------------------------------------
    # 1. Extend the part master.
    # ----------------------------------------------------------------------
    # Added with a server default so the statement succeeds against rows that
    # already exist, then the default is dropped: it was a migration device,
    # and leaving it behind would let future inserts silently skip a column the
    # application always sets.
    additions: list[tuple[str, sa.Column, str | None]] = [
        (
            "part_class",
            sa.Column(
                "part_class",
                _enum(
                    "Mechanical",
                    "Electrical",
                    "Electromechanical",
                    "Software",
                    "Raw material",
                    "Consumable",
                    "Packaging",
                    "Phantom",
                    "Assembly",
                    "Document",
                    name="part_class",
                    length=32,
                ),
                nullable=False,
                server_default="Mechanical",
            ),
            "Mechanical",
        ),
        (
            "unit_of_measure",
            sa.Column(
                "unit_of_measure", sa.String(length=16), nullable=False, server_default="ea"
            ),
            "ea",
        ),
        (
            "make_or_buy",
            sa.Column(
                "make_or_buy",
                _enum("Make", "Buy", "Make or buy", name="make_or_buy", length=16),
                nullable=False,
                server_default="Buy",
            ),
            "Buy",
        ),
        (
            "currency",
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
            "EUR",
        ),
        (
            "is_configuration_item",
            sa.Column(
                "is_configuration_item",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            "false",
        ),
        (
            "pfas_free",
            sa.Column(
                "pfas_free",
                _enum("Yes", "No", "Unknown", name="declaration", length=16),
                nullable=False,
                server_default="Unknown",
            ),
            "Unknown",
        ),
        (
            "contains_heavy_rare_earth",
            sa.Column(
                "contains_heavy_rare_earth",
                _enum("Yes", "No", "Unknown", name="declaration", length=16),
                nullable=False,
                server_default="Unknown",
            ),
            "Unknown",
        ),
        (
            "rohs_reach_status",
            sa.Column(
                "rohs_reach_status",
                _enum(
                    "Compliant",
                    "Non-compliant",
                    "Exempt",
                    "Unknown",
                    name="compliance_status",
                    length=16,
                ),
                nullable=False,
                server_default="Unknown",
            ),
            "Unknown",
        ),
    ]
    for _, column, _default in additions:
        op.add_column("parts", column)

    # Nullable from the start; no default needed.
    op.add_column("parts", sa.Column("standard_cost", sa.Numeric(precision=14, scale=4), nullable=True))
    op.add_column("parts", sa.Column("lead_time_days", sa.Integer(), nullable=True))
    op.add_column(
        "parts",
        sa.Column(
            "ci_criticality",
            _enum("Low", "Medium", "High", "Critical", name="ci_criticality", length=16),
            nullable=True,
        ),
    )
    op.add_column("parts", sa.Column("gwp_direct", sa.Float(), nullable=True))
    op.add_column("parts", sa.Column("external_ref", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_parts_external_ref"), "parts", ["external_ref"])

    # An item whose material is "Assembly" is one; classifying it as mechanical
    # would put sub-assemblies into the compliance rollup as if they carried
    # material of their own.
    op.execute(
        "UPDATE parts SET part_class = 'Assembly' WHERE material_type = 'Assembly'"
    )

    for name, _column, _default in additions:
        op.alter_column("parts", name, server_default=None)

    # ----------------------------------------------------------------------
    # 2. Revisions as rows.
    # ----------------------------------------------------------------------
    op.create_table(
        "part_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("part_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.String(length=16), nullable=False),
        sa.Column(
            "lifecycle_state",
            _enum(
                "In design",
                "In review",
                "Prototype",
                "Released",
                "Obsolete",
                name="lifecycle_state",
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.UUID(), nullable=True),
        sa.Column("superseded_by_id", sa.UUID(), nullable=True),
        sa.Column("created_by_eco_id", sa.UUID(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["part_id"], ["parts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"], ["part_revisions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("part_id", "revision", name="uq_part_revision"),
    )
    op.create_index("ix_part_revision_state", "part_revisions", ["part_id", "lifecycle_state"])
    op.create_index(
        op.f("ix_part_revisions_created_by_eco_id"), "part_revisions", ["created_by_eco_id"]
    )
    op.create_index(op.f("ix_part_revisions_part_id"), "part_revisions", ["part_id"])

    # Backfill: one released revision per existing part, carrying its string.
    op.execute(
        """
        INSERT INTO part_revisions
            (id, part_id, revision, lifecycle_state, released_at, created_at)
        SELECT gen_random_uuid(), p.id, p.revision, 'Released', p.created_at, p.created_at
        FROM parts p
        """
    )

    # ----------------------------------------------------------------------
    # 3. Typed, revision-bound BOM edges.
    # ----------------------------------------------------------------------
    op.create_table(
        "bom_edges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("parent_revision_id", sa.UUID(), nullable=False),
        sa.Column("child_part_id", sa.UUID(), nullable=False),
        sa.Column("child_revision_id", sa.UUID(), nullable=True),
        sa.Column("bom_type", _enum("EBOM", "MBOM", name="bom_type", length=8), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("unit_of_measure", sa.String(length=16), nullable=False),
        sa.Column("find_number", sa.String(length=32), nullable=True),
        sa.Column("reference_designator", sa.String(length=128), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("effective_from_serial", sa.String(length=64), nullable=True),
        sa.Column("eco_in_id", sa.UUID(), nullable=True),
        sa.Column("eco_out_id", sa.UUID(), nullable=True),
        sa.Column("operation_seq", sa.Integer(), nullable=True),
        sa.Column("is_phantom", sa.Boolean(), nullable=False),
        sa.Column("scrap_factor", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["child_part_id"], ["parts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["child_revision_id"], ["part_revisions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["parent_revision_id"], ["part_revisions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parent_revision_id",
            "child_part_id",
            "bom_type",
            "find_number",
            name="uq_bom_edge",
        ),
    )
    op.create_index("ix_bom_edge_child", "bom_edges", ["child_part_id", "bom_type"])
    op.create_index("ix_bom_edge_parent", "bom_edges", ["parent_revision_id", "bom_type"])

    # Backfill: every old edge becomes an EBOM line on the parent's one
    # backfilled revision. The join is unambiguous because step 2 created
    # exactly one revision per part.
    op.execute(
        """
        INSERT INTO bom_edges
            (id, parent_revision_id, child_part_id, bom_type, quantity,
             unit_of_measure, find_number, notes, is_phantom, scrap_factor)
        SELECT gen_random_uuid(), pr.id, a.child_part_id, 'EBOM', a.quantity,
               'ea', a.position_ref, a.notes, false, 0
        FROM assemblies a
        JOIN part_revisions pr ON pr.part_id = a.parent_part_id
        """
    )

    # ----------------------------------------------------------------------
    # 4. Manufacturing view, baselines, document vault.
    # ----------------------------------------------------------------------
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_number", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column(
            "kind",
            _enum(
                "CAD model",
                "Drawing",
                "Work instruction",
                "Test report",
                "Datasheet",
                "Certificate",
                "Specification",
                name="document_kind",
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("related_part_id", sa.UUID(), nullable=True),
        sa.Column("locked_by", sa.UUID(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["related_part_id"], ["parts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_documents_document_number"), "documents", ["document_number"], unique=True
    )

    op.create_table(
        "document_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.String(length=16), nullable=False),
        sa.Column("filename", sa.String(length=256), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("eco_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "revision", name="uq_document_revision"),
    )
    op.create_index(
        op.f("ix_document_revisions_content_hash"), "document_revisions", ["content_hash"]
    )
    op.create_index(
        op.f("ix_document_revisions_document_id"), "document_revisions", ["document_id"]
    )

    op.create_table(
        "mbom_deltas",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("root_revision_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column(
            "delta_type",
            _enum(
                "Add", "Remove", "Requantify", "Phantom", "Route",
                name="mbom_delta_type",
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("parent_part_id", sa.UUID(), nullable=True),
        sa.Column("child_part_id", sa.UUID(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("unit_of_measure", sa.String(length=16), nullable=True),
        sa.Column("operation_seq", sa.Integer(), nullable=True),
        sa.Column("is_phantom", sa.Boolean(), nullable=True),
        sa.Column("scrap_factor", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["child_part_id"], ["parts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_part_id"], ["parts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["root_revision_id"], ["part_revisions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mbom_delta_root", "mbom_deltas", ["root_revision_id", "sequence"])

    op.create_table(
        "operations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("root_revision_id", sa.UUID(), nullable=False),
        sa.Column("op_seq", sa.Integer(), nullable=False),
        sa.Column("work_center", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("setup_minutes", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("run_minutes", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("work_instruction_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["root_revision_id"], ["part_revisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["work_instruction_id"], ["documents.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("root_revision_id", "op_seq", name="uq_operation_seq"),
    )
    op.create_index(op.f("ix_operations_root_revision_id"), "operations", ["root_revision_id"])

    op.create_table(
        "configuration_baselines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=True),
        sa.Column("root_part_id", sa.UUID(), nullable=False),
        sa.Column("root_revision_id", sa.UUID(), nullable=False),
        sa.Column("bom_type", _enum("EBOM", "MBOM", name="bom_type", length=8), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("captured_by", sa.UUID(), nullable=True),
        sa.Column("eco_id", sa.UUID(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["root_part_id"], ["parts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["root_revision_id"], ["part_revisions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_baseline_name"),
    )
    op.create_index(
        op.f("ix_configuration_baselines_platform"), "configuration_baselines", ["platform"]
    )
    op.create_index(
        op.f("ix_configuration_baselines_root_part_id"),
        "configuration_baselines",
        ["root_part_id"],
    )

    # ----------------------------------------------------------------------
    # 5. Retire what the new structures replaced.
    # ----------------------------------------------------------------------
    op.drop_index(op.f("ix_assembly_parent"), table_name="assemblies")
    op.drop_table("assemblies")
    op.drop_column("parts", "revision")


def downgrade() -> None:
    # Restore the flat revision string from the released revision, or from
    # whichever revision is newest if none has been released.
    op.add_column("parts", sa.Column("revision", sa.VARCHAR(length=16), nullable=True))
    op.execute(
        """
        UPDATE parts p
        SET revision = sub.revision
        FROM (
            SELECT DISTINCT ON (part_id) part_id, revision
            FROM part_revisions
            ORDER BY part_id,
                     (lifecycle_state = 'Released') DESC,
                     released_at DESC NULLS LAST,
                     created_at DESC
        ) sub
        WHERE sub.part_id = p.id
        """
    )
    op.execute("UPDATE parts SET revision = 'A' WHERE revision IS NULL")
    op.alter_column("parts", "revision", nullable=False)

    op.create_table(
        "assemblies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("parent_part_id", sa.UUID(), nullable=False),
        sa.Column("child_part_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.INTEGER(), nullable=False),
        sa.Column("position_ref", sa.VARCHAR(length=32), nullable=True),
        sa.Column("notes", sa.TEXT(), nullable=True),
        sa.ForeignKeyConstraint(["child_part_id"], ["parts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_part_id"], ["parts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parent_part_id", "child_part_id", name="uq_assembly_edge"),
    )
    op.create_index(op.f("ix_assembly_parent"), "assemblies", ["parent_part_id"])
    # EBOM only, and one row per parent/child pair: the old unique constraint
    # cannot hold two find numbers for the same pair, and quantity was integral.
    op.execute(
        """
        INSERT INTO assemblies
            (id, parent_part_id, child_part_id, quantity, position_ref, notes)
        SELECT DISTINCT ON (pr.part_id, e.child_part_id)
               gen_random_uuid(), pr.part_id, e.child_part_id,
               GREATEST(1, ROUND(e.quantity)::int), e.find_number, e.notes
        FROM bom_edges e
        JOIN part_revisions pr ON pr.id = e.parent_revision_id
        WHERE e.bom_type = 'EBOM'
        ORDER BY pr.part_id, e.child_part_id, e.find_number NULLS LAST
        """
    )

    op.drop_index(op.f("ix_configuration_baselines_root_part_id"), table_name="configuration_baselines")
    op.drop_index(op.f("ix_configuration_baselines_platform"), table_name="configuration_baselines")
    op.drop_table("configuration_baselines")
    op.drop_index(op.f("ix_operations_root_revision_id"), table_name="operations")
    op.drop_table("operations")
    op.drop_index("ix_mbom_delta_root", table_name="mbom_deltas")
    op.drop_table("mbom_deltas")
    op.drop_index(op.f("ix_document_revisions_document_id"), table_name="document_revisions")
    op.drop_index(op.f("ix_document_revisions_content_hash"), table_name="document_revisions")
    op.drop_table("document_revisions")
    op.drop_index("ix_bom_edge_parent", table_name="bom_edges")
    op.drop_index("ix_bom_edge_child", table_name="bom_edges")
    op.drop_table("bom_edges")
    op.drop_index(op.f("ix_part_revisions_part_id"), table_name="part_revisions")
    op.drop_index(op.f("ix_part_revisions_created_by_eco_id"), table_name="part_revisions")
    op.drop_index("ix_part_revision_state", table_name="part_revisions")
    op.drop_table("part_revisions")
    op.drop_index(op.f("ix_documents_document_number"), table_name="documents")
    op.drop_table("documents")

    op.drop_index(op.f("ix_parts_external_ref"), table_name="parts")
    for column in (
        "external_ref",
        "gwp_direct",
        "rohs_reach_status",
        "contains_heavy_rare_earth",
        "pfas_free",
        "ci_criticality",
        "is_configuration_item",
        "lead_time_days",
        "currency",
        "standard_cost",
        "make_or_buy",
        "unit_of_measure",
        "part_class",
    ):
        op.drop_column("parts", column)
