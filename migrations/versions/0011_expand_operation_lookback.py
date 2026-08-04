"""Allow a daily operation to cover the current quarter.

Revision ID: 0011_operation_lookback
Revises: 0010_portfolio_units
"""

from __future__ import annotations

from alembic import op

revision: str = "0011_operation_lookback"
down_revision: str | None = "0010_portfolio_units"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("data_operation") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_data_operation_lookback_days_range"),
            type_="check",
        )
        batch_op.create_check_constraint(
            op.f("ck_data_operation_lookback_days_range"),
            "lookback_days BETWEEN 1 AND 100",
        )


def downgrade() -> None:
    with op.batch_alter_table("data_operation") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_data_operation_lookback_days_range"),
            type_="check",
        )
        batch_op.create_check_constraint(
            op.f("ck_data_operation_lookback_days_range"),
            "lookback_days BETWEEN 1 AND 30",
        )
