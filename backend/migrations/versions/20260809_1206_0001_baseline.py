"""baseline: pdm, qms, knowledge, identity, audit, proposals

Revision ID: 0001_baseline
Revises:
Created: 2026-08-09

The starting schema: the PDM part master and BOM edge table, QMS lab test
records, the pgvector knowledge corpus, users and roles, the append-only audit
log, and the agent proposal queue.

The IVFFlat index on `knowledge_embeddings.embedding` is deliberately absent.
It is created by `app.core.db.create_vector_index` *after* seeding, because
IVFFlat derives its cluster centroids from the rows present when it is built and
an index created against an empty table gives poor recall. `migrations/env.py`
excludes it from autogenerate so later revisions do not script a DROP for it.
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy import String, Text
from sqlalchemy.dialects import postgresql

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_proposals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("proposed_by_agent", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("arguments", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("preview", postgresql.JSONB(astext_type=Text()), nullable=False),
        sa.Column("required_role", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                "applied",
                "failed",
                name="proposal_status",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_proposals_correlation_id"),
        "agent_proposals",
        ["correlation_id"],
    )
    op.create_index(
        op.f("ix_agent_proposals_created_at"), "agent_proposals", ["created_at"]
    )
    op.create_index(op.f("ix_agent_proposals_status"), "agent_proposals", ["status"])
    op.create_index(
        op.f("ix_agent_proposals_tool_name"), "agent_proposals", ["tool_name"]
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "actor_type",
            sa.Enum(
                "human",
                "agent",
                "system",
                name="actor_type",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_label", sa.String(length=128), nullable=False),
        sa.Column(
            "action",
            sa.Enum(
                "create",
                "update",
                "delete",
                "transition",
                "approve",
                "reject",
                "login",
                name="audit_action",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_entity", "audit_events", ["entity_type", "entity_id", "occurred_at"]
    )
    op.create_index(
        op.f("ix_audit_events_correlation_id"), "audit_events", ["correlation_id"]
    )
    op.create_index(
        op.f("ix_audit_events_occurred_at"), "audit_events", ["occurred_at"]
    )
    op.create_index("ix_audit_occurred", "audit_events", ["occurred_at"])

    op.create_table(
        "parts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("part_number", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "material_type",
            sa.Enum(
                "LaFeSi",
                "Neodymium",
                "Polymer",
                "Fluid",
                "Composite",
                "Steel",
                "Assembly",
                name="material_type",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "coating_status",
            sa.Enum(
                "Anti-corrosion metal coating",
                "Epoxy bonded",
                "Passivated",
                "Uncoated",
                "N/A",
                name="coating_status",
                native_enum=False,
                length=48,
            ),
            nullable=False,
        ),
        sa.Column("revision", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_parts_part_number"), "parts", ["part_number"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("roles", postgresql.ARRAY(String(length=32)), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "assemblies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("parent_part_id", sa.UUID(), nullable=False),
        sa.Column("child_part_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("position_ref", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["child_part_id"], ["parts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_part_id"], ["parts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parent_part_id", "child_part_id", name="uq_assembly_edge"),
    )
    op.create_index("ix_assembly_parent", "assemblies", ["parent_part_id"])

    op.create_table(
        "knowledge_embeddings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1536), nullable=False
        ),
        sa.Column("related_part_id", sa.UUID(), nullable=True),
        sa.Column(
            "document_type",
            sa.Enum(
                "ECO",
                "Test Failure",
                "Spec",
                "Field Report",
                name="document_type",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["related_part_id"], ["parts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "lab_test_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("serial_number", sa.String(length=64), nullable=False),
        sa.Column("part_id", sa.UUID(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        # Spec casing retained end to end; see app/domains/qms/models.py.
        sa.Column("temperature_span_delta_K", sa.Float(), nullable=False),
        sa.Column("pressure_drop_mbar", sa.Float(), nullable=False),
        sa.Column("magnetization_cycles_hz", sa.Float(), nullable=False),
        sa.Column("cooling_capacity_W", sa.Float(), nullable=False),
        sa.Column("test_rig", sa.String(length=64), nullable=True),
        sa.Column("operator", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["part_id"], ["parts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_lab_serial_time", "lab_test_records", ["serial_number", "recorded_at"]
    )
    op.create_index(
        op.f("ix_lab_test_records_recorded_at"), "lab_test_records", ["recorded_at"]
    )
    op.create_index(
        op.f("ix_lab_test_records_serial_number"), "lab_test_records", ["serial_number"]
    )


def downgrade() -> None:
    # Dropped children-first so the foreign keys go with them.
    op.drop_table("lab_test_records")
    op.drop_table("knowledge_embeddings")
    op.drop_table("assemblies")
    op.drop_table("users")
    op.drop_table("parts")
    op.drop_table("audit_events")
    op.drop_table("agent_proposals")
