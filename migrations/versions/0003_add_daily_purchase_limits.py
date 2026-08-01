"""Add source-specific daily sales-channel purchase-limit snapshots.

Revision ID: 0003_add_daily_purchase_limits
Revises: 0002_preserve_allocation_rows
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_add_daily_purchase_limits"
down_revision: str | None = "0002_preserve_allocation_rows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_purchase_limit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_share_id",
            sa.Integer(),
            sa.ForeignKey("fund_share.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("channel_type", sa.String(20), nullable=False),
        sa.Column("channel_key", sa.String(100), nullable=False),
        sa.Column("channel_name", sa.String(200), nullable=False),
        sa.Column("business_type", sa.String(40), nullable=False),
        sa.Column("availability_state", sa.String(30), nullable=False),
        sa.Column("cap_state", sa.String(20), nullable=False),
        sa.Column("daily_limit_amount", sa.Numeric(24, 6)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="CNY"),
        sa.Column("limit_basis", sa.String(50), nullable=False),
        sa.Column("share_scope", sa.String(50), nullable=False),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("source_provider", sa.String(100), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_published_at", sa.DateTime(timezone=True)),
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
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.CheckConstraint(
            "channel_type IN ('DIRECT', 'DISTRIBUTION')",
            name="ck_daily_purchase_limit_channel_type_allowed",
        ),
        sa.CheckConstraint(
            "length(trim(channel_key)) > 0",
            name="ck_daily_purchase_limit_channel_key_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(channel_name)) > 0",
            name="ck_daily_purchase_limit_channel_name_nonempty",
        ),
        sa.CheckConstraint(
            "business_type IN ('PURCHASE', 'RECURRING_INVESTMENT', 'CONVERSION_IN')",
            name="ck_daily_purchase_limit_business_type_allowed",
        ),
        sa.CheckConstraint(
            "availability_state IN "
            "('OPEN', 'PAUSED', 'UNKNOWN', 'NOT_SOLD', 'NOT_APPLICABLE')",
            name="ck_daily_purchase_limit_availability_state_allowed",
        ),
        sa.CheckConstraint(
            "cap_state IN ('LIMITED', 'UNLIMITED', 'UNKNOWN')",
            name="ck_daily_purchase_limit_cap_state_allowed",
        ),
        sa.CheckConstraint(
            "limit_basis IN ('PER_ACCOUNT_PER_DAY', 'UNKNOWN')",
            name="ck_daily_purchase_limit_limit_basis_allowed",
        ),
        sa.CheckConstraint(
            "share_scope IN ('PER_SHARE', 'ALL_SHARES_COMBINED', 'UNKNOWN')",
            name="ck_daily_purchase_limit_share_scope_allowed",
        ),
        sa.CheckConstraint(
            "(cap_state = 'LIMITED' AND daily_limit_amount IS NOT NULL "
            "AND daily_limit_amount > 0) OR "
            "(cap_state IN ('UNLIMITED', 'UNKNOWN') AND daily_limit_amount IS NULL)",
            name="ck_daily_purchase_limit_amount_matches_cap_state",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_daily_purchase_limit_currency_format",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="ck_daily_purchase_limit_effective_date_order",
        ),
        sa.CheckConstraint(
            "length(trim(source_provider)) > 0",
            name="ck_daily_purchase_limit_source_provider_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(source_url)) > 0",
            name="ck_daily_purchase_limit_source_url_nonempty",
        ),
        sa.CheckConstraint(
            "length(raw_payload_hash) = 64",
            name="ck_daily_purchase_limit_raw_payload_hash_length",
        ),
        sa.CheckConstraint(
            "length(trim(raw_text)) > 0",
            name="ck_daily_purchase_limit_raw_text_nonempty",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_daily_purchase_limit_confidence_range",
        ),
        sa.UniqueConstraint(
            "fund_share_id",
            "snapshot_date",
            "channel_type",
            "channel_key",
            "business_type",
            "limit_basis",
            "share_scope",
            "source_provider",
            name="uq_daily_purchase_limit_identity",
        ),
    )
    op.create_index(
        "ix_daily_purchase_limit_snapshot_date",
        "daily_purchase_limit",
        ["snapshot_date"],
    )
    op.create_index(
        "ix_daily_purchase_limit_source_artifact_id",
        "daily_purchase_limit",
        ["source_artifact_id"],
    )
    op.create_index(
        "ix_daily_purchase_limit_share_snapshot",
        "daily_purchase_limit",
        ["fund_share_id", "snapshot_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_purchase_limit_share_snapshot", table_name="daily_purchase_limit")
    op.drop_index("ix_daily_purchase_limit_source_artifact_id", table_name="daily_purchase_limit")
    op.drop_index("ix_daily_purchase_limit_snapshot_date", table_name="daily_purchase_limit")
    op.drop_table("daily_purchase_limit")
