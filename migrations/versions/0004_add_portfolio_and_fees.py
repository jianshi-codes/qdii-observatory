"""Add local portfolio snapshots and daily fee observations.

Revision ID: 0004_add_portfolio_and_fees
Revises: 0003_add_daily_purchase_limits
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_portfolio_and_fees"
down_revision: str | None = "0003_add_daily_purchase_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_fund_fee",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_share_id",
            sa.Integer(),
            sa.ForeignKey("fund_share.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("management_fee_pct_annual", sa.Numeric(14, 8)),
        sa.Column("custody_fee_pct_annual", sa.Numeric(14, 8)),
        sa.Column("sales_service_fee_pct_annual", sa.Numeric(14, 8)),
        sa.Column("standard_purchase_fee_pct", sa.Numeric(14, 8)),
        sa.Column("discounted_purchase_fee_pct", sa.Numeric(14, 8)),
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
            "management_fee_pct_annual IS NULL OR management_fee_pct_annual BETWEEN 0 AND 100",
            name="ck_daily_fund_fee_management_fee_range",
        ),
        sa.CheckConstraint(
            "custody_fee_pct_annual IS NULL OR custody_fee_pct_annual BETWEEN 0 AND 100",
            name="ck_daily_fund_fee_custody_fee_range",
        ),
        sa.CheckConstraint(
            "sales_service_fee_pct_annual IS NULL OR "
            "sales_service_fee_pct_annual BETWEEN 0 AND 100",
            name="ck_daily_fund_fee_sales_service_fee_range",
        ),
        sa.CheckConstraint(
            "standard_purchase_fee_pct IS NULL OR standard_purchase_fee_pct BETWEEN 0 AND 100",
            name="ck_daily_fund_fee_standard_purchase_fee_range",
        ),
        sa.CheckConstraint(
            "discounted_purchase_fee_pct IS NULL OR discounted_purchase_fee_pct BETWEEN 0 AND 100",
            name="ck_daily_fund_fee_discounted_purchase_fee_range",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="ck_daily_fund_fee_confidence_range",
        ),
        sa.UniqueConstraint(
            "fund_share_id",
            "snapshot_date",
            "source_provider",
            name="uq_daily_fund_fee_identity",
        ),
    )
    op.create_index("ix_daily_fund_fee_fund_share_id", "daily_fund_fee", ["fund_share_id"])
    op.create_index("ix_daily_fund_fee_snapshot_date", "daily_fund_fee", ["snapshot_date"])
    op.create_index(
        "ix_daily_fund_fee_source_artifact_id", "daily_fund_fee", ["source_artifact_id"]
    )

    op.create_table(
        "portfolio_position",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_share_id",
            sa.Integer(),
            sa.ForeignKey("fund_share.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(100), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reported_market_value", sa.Numeric(24, 6), nullable=False),
        sa.Column("reported_profit_amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("reported_return_pct", sa.Numeric(14, 8), nullable=False),
        sa.Column("reported_cumulative_profit_amount", sa.Numeric(24, 6)),
        sa.Column("anchor_nav_date", sa.Date(), nullable=False),
        sa.Column("anchor_unit_nav", sa.Numeric(24, 8), nullable=False),
        sa.Column("recurring_frequency", sa.String(20)),
        sa.Column("recurring_gross_amount", sa.Numeric(24, 6)),
        sa.Column("recurring_fee_pct", sa.Numeric(14, 8)),
        sa.Column("recurring_net_amount", sa.Numeric(24, 6)),
        sa.Column("manual_purchase_fee_pct", sa.Numeric(14, 8)),
        sa.Column("manual_management_fee_pct_annual", sa.Numeric(14, 8)),
        sa.Column("manual_custody_fee_pct_annual", sa.Numeric(14, 8)),
        sa.Column("source_type", sa.String(40), nullable=False, server_default="USER_REPORTED"),
        sa.Column("data_quality_note", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "length(trim(platform)) > 0",
            name="ck_portfolio_position_platform_nonempty",
        ),
        sa.CheckConstraint(
            "reported_market_value > 0",
            name="ck_portfolio_position_market_value_positive",
        ),
        sa.CheckConstraint(
            "anchor_unit_nav > 0",
            name="ck_portfolio_position_anchor_unit_nav_positive",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_portfolio_position_currency_format",
        ),
        sa.CheckConstraint(
            "recurring_frequency IS NULL OR recurring_frequency = 'DAILY'",
            name="ck_portfolio_position_recurring_frequency_allowed",
        ),
        sa.CheckConstraint(
            "recurring_gross_amount IS NULL OR recurring_gross_amount > 0",
            name="ck_portfolio_position_recurring_gross_amount_positive",
        ),
        sa.CheckConstraint(
            "recurring_fee_pct IS NULL OR recurring_fee_pct BETWEEN 0 AND 100",
            name="ck_portfolio_position_recurring_fee_range",
        ),
        sa.CheckConstraint(
            "recurring_net_amount IS NULL OR recurring_net_amount > 0",
            name="ck_portfolio_position_recurring_net_amount_positive",
        ),
        sa.CheckConstraint(
            "manual_purchase_fee_pct IS NULL OR manual_purchase_fee_pct BETWEEN 0 AND 100",
            name="ck_portfolio_position_manual_purchase_fee_range",
        ),
        sa.CheckConstraint(
            "manual_management_fee_pct_annual IS NULL OR "
            "manual_management_fee_pct_annual BETWEEN 0 AND 100",
            name="ck_portfolio_position_manual_management_fee_range",
        ),
        sa.CheckConstraint(
            "manual_custody_fee_pct_annual IS NULL OR "
            "manual_custody_fee_pct_annual BETWEEN 0 AND 100",
            name="ck_portfolio_position_manual_custody_fee_range",
        ),
        sa.UniqueConstraint(
            "platform",
            "fund_share_id",
            name="uq_portfolio_position_platform_share",
        ),
    )
    op.create_index(
        "ix_portfolio_position_fund_share_id", "portfolio_position", ["fund_share_id"]
    )
    op.create_index("ix_portfolio_position_platform", "portfolio_position", ["platform"])
    op.create_index("ix_portfolio_position_is_active", "portfolio_position", ["is_active"])

    op.create_table(
        "portfolio_cash_flow",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "portfolio_position_id",
            sa.Integer(),
            sa.ForeignKey("portfolio_position.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("flow_type", sa.String(30), nullable=False),
        sa.Column("occurred_on", sa.Date()),
        sa.Column("occurred_year", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(24, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False, server_default="USER_REPORTED"),
        sa.Column("note", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "flow_type = 'DIVIDEND'",
            name="ck_portfolio_cash_flow_flow_type_allowed",
        ),
        sa.CheckConstraint(
            "occurred_year BETWEEN 2000 AND 2100",
            name="ck_portfolio_cash_flow_occurred_year_range",
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_portfolio_cash_flow_amount_positive",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_portfolio_cash_flow_currency_format",
        ),
    )
    op.create_index(
        "ix_portfolio_cash_flow_portfolio_position_id",
        "portfolio_cash_flow",
        ["portfolio_position_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_portfolio_cash_flow_portfolio_position_id", table_name="portfolio_cash_flow"
    )
    op.drop_table("portfolio_cash_flow")
    op.drop_index("ix_portfolio_position_is_active", table_name="portfolio_position")
    op.drop_index("ix_portfolio_position_platform", table_name="portfolio_position")
    op.drop_index("ix_portfolio_position_fund_share_id", table_name="portfolio_position")
    op.drop_table("portfolio_position")
    op.drop_index("ix_daily_fund_fee_source_artifact_id", table_name="daily_fund_fee")
    op.drop_index("ix_daily_fund_fee_snapshot_date", table_name="daily_fund_fee")
    op.drop_index("ix_daily_fund_fee_fund_share_id", table_name="daily_fund_fee")
    op.drop_table("daily_fund_fee")
