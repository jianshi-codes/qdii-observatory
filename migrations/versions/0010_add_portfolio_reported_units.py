"""Make user-reported holding units the portfolio valuation anchor.

Revision ID: 0010_portfolio_units
Revises: 0009_recurring_order_state
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0010_portfolio_units"
down_revision: str | None = "0009_recurring_order_state"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    with op.batch_alter_table("portfolio_position") as batch_op:
        batch_op.add_column(sa.Column("reported_units", sa.Numeric(28, 8), nullable=True))
    op.execute(
        sa.text(
            "UPDATE portfolio_position "
            "SET reported_units = reported_market_value / anchor_unit_nav "
            "WHERE reported_units IS NULL"
        )
    )
    with op.batch_alter_table("portfolio_position") as batch_op:
        batch_op.alter_column("reported_units", existing_type=sa.Numeric(28, 8), nullable=False)
        batch_op.create_check_constraint(
            op.f("ck_portfolio_position_reported_units_positive"),
            "reported_units > 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("portfolio_position") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_portfolio_position_reported_units_positive"),
            type_="check",
        )
        batch_op.drop_column("reported_units")
