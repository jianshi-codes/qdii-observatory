"""Add pending recurring-investment orders and confirmation state.

Revision ID: 0009_recurring_order_state
Revises: 0008_recurring_execution
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009_recurring_order_state"
down_revision: str | None = "0008_recurring_execution"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("portfolio_position") as batch_op:
        batch_op.add_column(
            sa.Column(
                "recurring_confirmation_lag_days",
                sa.Integer(),
                server_default="2",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            op.f("ck_portfolio_position_recurring_confirmation_lag_days_range"),
            "recurring_confirmation_lag_days BETWEEN 0 AND 10",
        )
    op.create_table(
        "portfolio_recurring_order",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_position_id", sa.Integer(), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_confirmation_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("gross_amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("fee_pct", sa.Numeric(14, 8), nullable=False),
        sa.Column("net_amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("settled_execution_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('PENDING', 'SETTLED')",
            name=op.f("ck_portfolio_recurring_order_status_allowed"),
        ),
        sa.CheckConstraint(
            "gross_amount > 0",
            name=op.f("ck_portfolio_recurring_order_gross_amount_positive"),
        ),
        sa.CheckConstraint(
            "fee_pct BETWEEN 0 AND 100",
            name=op.f("ck_portfolio_recurring_order_fee_range"),
        ),
        sa.CheckConstraint(
            "net_amount > 0",
            name=op.f("ck_portfolio_recurring_order_net_amount_positive"),
        ),
        sa.CheckConstraint(
            "expected_confirmation_date >= order_date",
            name=op.f("ck_portfolio_recurring_order_expected_confirmation_not_before_order"),
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND settled_execution_id IS NULL AND confirmed_at IS NULL) OR "
            "(status = 'SETTLED' AND settled_execution_id IS NOT NULL AND confirmed_at IS NOT NULL)",
            name=op.f("ck_portfolio_recurring_order_settlement_state_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_position_id"],
            ["portfolio_position.id"],
            name=op.f("fk_portfolio_recurring_order_portfolio_position_id_portfolio_position"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["settled_execution_id"],
            ["portfolio_recurring_execution.id"],
            name=op.f(
                "fk_portfolio_recurring_order_settled_execution_id_portfolio_recurring_execution"
            ),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_recurring_order")),
        sa.UniqueConstraint(
            "portfolio_position_id",
            "order_date",
            name=op.f("uq_portfolio_recurring_order_position_order_date"),
        ),
        sa.UniqueConstraint(
            "settled_execution_id",
            name=op.f("uq_portfolio_recurring_order_settled_execution"),
        ),
    )
    op.create_index(
        op.f("ix_portfolio_recurring_order_portfolio_position_id"),
        "portfolio_recurring_order",
        ["portfolio_position_id"],
    )
    op.create_index(
        op.f("ix_portfolio_recurring_order_order_date"),
        "portfolio_recurring_order",
        ["order_date"],
    )
    op.create_index(
        op.f("ix_portfolio_recurring_order_expected_confirmation_date"),
        "portfolio_recurring_order",
        ["expected_confirmation_date"],
    )
    op.create_index(
        op.f("ix_portfolio_recurring_order_status"),
        "portfolio_recurring_order",
        ["status"],
    )
    op.create_index(
        op.f("ix_portfolio_recurring_order_settled_execution_id"),
        "portfolio_recurring_order",
        ["settled_execution_id"],
    )
    op.add_column(
        "data_operation",
        sa.Column("recurring_orders_created", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "data_operation",
        sa.Column("recurring_orders_settled", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("data_operation", "recurring_orders_settled")
    op.drop_column("data_operation", "recurring_orders_created")
    op.drop_index(
        op.f("ix_portfolio_recurring_order_settled_execution_id"),
        table_name="portfolio_recurring_order",
    )
    op.drop_index(
        op.f("ix_portfolio_recurring_order_status"),
        table_name="portfolio_recurring_order",
    )
    op.drop_index(
        op.f("ix_portfolio_recurring_order_expected_confirmation_date"),
        table_name="portfolio_recurring_order",
    )
    op.drop_index(
        op.f("ix_portfolio_recurring_order_order_date"),
        table_name="portfolio_recurring_order",
    )
    op.drop_index(
        op.f("ix_portfolio_recurring_order_portfolio_position_id"),
        table_name="portfolio_recurring_order",
    )
    op.drop_table("portfolio_recurring_order")
    with op.batch_alter_table("portfolio_position") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_portfolio_position_recurring_confirmation_lag_days_range"),
            type_="check",
        )
        batch_op.drop_column("recurring_confirmation_lag_days")
