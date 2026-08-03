"""Add durable user-requested data operations.

Revision ID: 0007_add_data_operations
Revises: 0006_generalize_universe
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007_add_data_operations"
down_revision: str | None = "0006_generalize_universe"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "data_operation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("fund_codes", sa.JSON(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column("report_year", sa.Integer(), nullable=True),
        sa.Column("report_quarter", sa.Integer(), nullable=True),
        sa.Column("current_stage", sa.String(length=50), nullable=True),
        sa.Column("stage_completed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stage_total", sa.Integer(), nullable=False),
        sa.Column("run_ids", sa.JSON(), nullable=False),
        sa.Column("records_written", sa.Integer(), server_default="0", nullable=False),
        sa.Column("records_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "operation IN ('prepare', 'sync-daily', 'sync-sales-limits', "
            "'sync-reports', 'parse-reports')",
            name=op.f("ck_data_operation_operation_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial', 'failed')",
            name=op.f("ck_data_operation_status_allowed"),
        ),
        sa.CheckConstraint(
            "(status IN ('queued', 'running') AND active_slot = 1) OR "
            "(status IN ('succeeded', 'partial', 'failed') AND active_slot IS NULL)",
            name=op.f("ck_data_operation_active_slot_matches_status"),
        ),
        sa.CheckConstraint(
            "lookback_days BETWEEN 1 AND 30",
            name=op.f("ck_data_operation_lookback_days_range"),
        ),
        sa.CheckConstraint(
            "report_quarter IS NULL OR report_quarter BETWEEN 1 AND 4",
            name=op.f("ck_data_operation_report_quarter_range"),
        ),
        sa.CheckConstraint(
            "stage_completed >= 0 AND stage_total >= 1 AND stage_completed <= stage_total",
            name=op.f("ck_data_operation_stage_progress_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_operation")),
        sa.UniqueConstraint("active_slot", name=op.f("uq_data_operation_active_slot")),
    )
    op.create_index("ix_data_operation_operation", "data_operation", ["operation"])
    op.create_index("ix_data_operation_status", "data_operation", ["status"])


def downgrade() -> None:
    op.drop_index("ix_data_operation_status", table_name="data_operation")
    op.drop_index("ix_data_operation_operation", table_name="data_operation")
    op.drop_table("data_operation")
