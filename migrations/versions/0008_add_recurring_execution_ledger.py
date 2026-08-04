"""Add idempotent portfolio recurring-investment executions.

Revision ID: 0008_recurring_execution
Revises: 0007_add_data_operations
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008_recurring_execution"
down_revision: str | None = "0007_add_data_operations"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_recurring_execution",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_position_id", sa.Integer(), nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("unit_nav", sa.Numeric(24, 8), nullable=False),
        sa.Column("gross_amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("fee_pct", sa.Numeric(14, 8), nullable=False),
        sa.Column("net_amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("units", sa.Numeric(28, 8), nullable=False),
        sa.Column("source_provider", sa.String(length=100), nullable=False),
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
            "unit_nav > 0", name=op.f("ck_portfolio_recurring_execution_unit_nav_positive")
        ),
        sa.CheckConstraint(
            "gross_amount > 0", name=op.f("ck_portfolio_recurring_execution_gross_amount_positive")
        ),
        sa.CheckConstraint(
            "fee_pct BETWEEN 0 AND 100", name=op.f("ck_portfolio_recurring_execution_fee_range")
        ),
        sa.CheckConstraint(
            "net_amount > 0", name=op.f("ck_portfolio_recurring_execution_net_amount_positive")
        ),
        sa.CheckConstraint(
            "units > 0", name=op.f("ck_portfolio_recurring_execution_units_positive")
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_position_id"],
            ["portfolio_position.id"],
            name=op.f("fk_portfolio_recurring_execution_portfolio_position_id_portfolio_position"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_recurring_execution")),
        sa.UniqueConstraint(
            "portfolio_position_id",
            "nav_date",
            name=op.f("uq_portfolio_recurring_execution_position_nav_date"),
        ),
    )
    op.create_index(
        op.f("ix_portfolio_recurring_execution_portfolio_position_id"),
        "portfolio_recurring_execution",
        ["portfolio_position_id"],
    )
    op.create_index(
        op.f("ix_portfolio_recurring_execution_nav_date"),
        "portfolio_recurring_execution",
        ["nav_date"],
    )
    op.add_column(
        "data_operation",
        sa.Column("recurring_executions_written", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "data_operation",
        sa.Column("recurring_positions_updated", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "data_operation",
        sa.Column("recurring_latest_nav_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("data_operation", "recurring_latest_nav_date")
    op.drop_column("data_operation", "recurring_positions_updated")
    op.drop_column("data_operation", "recurring_executions_written")
    op.drop_index(
        op.f("ix_portfolio_recurring_execution_nav_date"),
        table_name="portfolio_recurring_execution",
    )
    op.drop_index(
        op.f("ix_portfolio_recurring_execution_portfolio_position_id"),
        table_name="portfolio_recurring_execution",
    )
    op.drop_table("portfolio_recurring_execution")
