"""Add the provider-neutral fund region field.

Revision ID: 0006_generalize_universe
Revises: 0005_add_daily_exchange_rates
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006_generalize_universe"
down_revision: str | None = "0005_add_daily_exchange_rates"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("fund_contract", sa.Column("region", sa.String(length=100), nullable=True))
    op.create_index("ix_fund_contract_region", "fund_contract", ["region"])


def downgrade() -> None:
    op.drop_index("ix_fund_contract_region", table_name="fund_contract")
    op.drop_column("fund_contract", "region")
