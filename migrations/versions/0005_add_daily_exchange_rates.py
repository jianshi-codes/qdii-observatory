"""Add source-backed daily exchange rates.

Revision ID: 0005_add_daily_exchange_rates
Revises: 0004_add_portfolio_and_fees
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_add_daily_exchange_rates"
down_revision: str | None = "0004_add_portfolio_and_fees"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_exchange_rate",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("quote_currency", sa.String(3), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(24, 12), nullable=False),
        sa.Column("source_provider", sa.String(100), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "source_artifact_id",
            sa.Integer(),
            sa.ForeignKey("source_artifact.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("raw_payload_hash", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.CheckConstraint(
            "base_currency <> quote_currency",
            name="ck_daily_exchange_rate_currencies_differ",
        ),
        sa.CheckConstraint("rate > 0", name="ck_daily_exchange_rate_rate_positive"),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="ck_daily_exchange_rate_confidence_range",
        ),
        sa.UniqueConstraint(
            "base_currency",
            "quote_currency",
            "rate_date",
            "source_provider",
            name="uq_daily_exchange_rate_identity",
        ),
    )
    op.create_index(
        "ix_daily_exchange_rate_base_currency", "daily_exchange_rate", ["base_currency"]
    )
    op.create_index(
        "ix_daily_exchange_rate_quote_currency", "daily_exchange_rate", ["quote_currency"]
    )
    op.create_index("ix_daily_exchange_rate_rate_date", "daily_exchange_rate", ["rate_date"])
    op.create_index(
        "ix_daily_exchange_rate_source_artifact_id",
        "daily_exchange_rate",
        ["source_artifact_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_exchange_rate_source_artifact_id", table_name="daily_exchange_rate")
    op.drop_index("ix_daily_exchange_rate_rate_date", table_name="daily_exchange_rate")
    op.drop_index("ix_daily_exchange_rate_quote_currency", table_name="daily_exchange_rate")
    op.drop_index("ix_daily_exchange_rate_base_currency", table_name="daily_exchange_rate")
    op.drop_table("daily_exchange_rate")
