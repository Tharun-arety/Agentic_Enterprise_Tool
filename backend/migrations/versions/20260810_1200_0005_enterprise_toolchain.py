"""enterprise phases 4-7

Revision ID: 0005_enterprise
Revises: 0004_qms
"""
from __future__ import annotations
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op
from app.core.db import Base
from app import model_registry  # noqa: F401

revision: str="0005_enterprise"
down_revision: str|None="0004_qms"
branch_labels: str|Sequence[str]|None=None
depends_on: str|Sequence[str]|None=None

NEW_TABLES={
"refresh_sessions","access_token_revocations","agent_runs","tool_invocations","eval_runs","eval_case_results","automation_findings","source_documents","source_document_versions","document_chunks","external_references","integration_outbox","webhook_inbox","suppliers","purchase_orders","purchase_order_lines","goods_receipts","receipt_lots","stock_positions","crm_leads","crm_opportunities","customer_sites","deployed_units","field_events","programs","work_packages","trl_gates","consortium_partners","deliverables","milestones","lab_assets","calibration_certificates","asset_bookings","test_asset_usage","engineer_capacity","resource_allocations","timesheet_entries","work_centre_rates","cost_centres","budgets","commitments","actuals","cost_targets","cost_rollup_snapshots"
}

def upgrade()->None:
    bind=op.get_bind()
    # Metadata is deliberately used as the canonical declaration: contract
    # tests and clean installs therefore build byte-for-byte equivalent tables.
    for table in Base.metadata.sorted_tables:
        if table.name in NEW_TABLES: table.create(bind=bind,checkfirst=True)
    inspector=sa.inspect(bind); columns={x["name"] for x in inspector.get_columns("lab_test_records")}
    if "is_valid" not in columns: op.add_column("lab_test_records",sa.Column("is_valid",sa.Boolean(),nullable=False,server_default=sa.true()))
    if "invalid_reason" not in columns: op.add_column("lab_test_records",sa.Column("invalid_reason",sa.Text(),nullable=True))
    if not any(x["name"]=="ix_lab_test_records_is_valid" for x in inspector.get_indexes("lab_test_records")): op.create_index("ix_lab_test_records_is_valid","lab_test_records",["is_valid"])

def downgrade()->None:
    op.drop_index("ix_lab_test_records_is_valid",table_name="lab_test_records"); op.drop_column("lab_test_records","invalid_reason"); op.drop_column("lab_test_records","is_valid")
    bind=op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in NEW_TABLES: table.drop(bind=bind,checkfirst=True)
