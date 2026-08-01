"""Create the complete initial QDII observatory schema.

Revision ID: 0001_initial_schema
Revises: None
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
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
    )


def _report_row_columns() -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("fair_value_cny", sa.Numeric(24, 6)),
        sa.Column("nav_pct", sa.Numeric(14, 8)),
        sa.Column("rank", sa.Integer()),
        sa.Column("source_section", sa.String(300), nullable=False),
        sa.Column("raw_row", sa.JSON(), nullable=False),
        sa.Column("parse_confidence", sa.Numeric(5, 4)),
    )


def upgrade() -> None:
    op.create_table(
        "fund_contract",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("canonical_name", sa.String(300), nullable=False),
        sa.Column("manager_name", sa.String(200), nullable=False),
        sa.Column("representative_code", sa.String(6), nullable=False),
        sa.Column("strategy_type", sa.String(100)),
        sa.Column("original_category", sa.String(100)),
        sa.Column("wrapper_type", sa.String(50)),
        sa.Column("tech_scope", sa.String(50), nullable=False, server_default="UNKNOWN"),
        sa.Column("is_user_selected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_dependency", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.CheckConstraint(
            "length(representative_code) = 6",
            name="ck_fund_contract_representative_code_length",
        ),
    )
    op.create_index(
        "ix_fund_contract_representative_code",
        "fund_contract",
        ["representative_code"],
        unique=True,
    )
    op.create_index("ix_fund_contract_original_category", "fund_contract", ["original_category"])
    op.create_index("ix_fund_contract_wrapper_type", "fund_contract", ["wrapper_type"])
    op.create_index("ix_fund_contract_tech_scope", "fund_contract", ["tech_scope"])
    op.create_index("ix_fund_contract_is_user_selected", "fund_contract", ["is_user_selected"])
    op.create_index("ix_fund_contract_is_dependency", "fund_contract", ["is_dependency"])

    op.create_table(
        "exposure_family",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        *_timestamps(),
        sa.UniqueConstraint("code", name="uq_exposure_family_code"),
    )

    op.create_table(
        "ingestion_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("records_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_ingestion_run_job_type", "ingestion_run", ["job_type"])
    op.create_index("ix_ingestion_run_status", "ingestion_run", ["status"])
    op.create_index("ix_ingestion_run_started_at", "ingestion_run", ["started_at"])

    op.create_table(
        "fund_share",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_contract_id",
            sa.Integer(),
            sa.ForeignKey("fund_contract.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("share_code", sa.String(6), nullable=False),
        sa.Column("share_class", sa.String(50)),
        sa.Column("currency", sa.String(10), nullable=False, server_default="CNY"),
        sa.Column("is_exchange_traded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("exchange", sa.String(30)),
        *_timestamps(),
        sa.CheckConstraint("length(share_code) = 6", name="ck_fund_share_share_code_length"),
    )
    op.create_index("ix_fund_share_fund_contract_id", "fund_share", ["fund_contract_id"])
    op.create_index("ix_fund_share_share_code", "fund_share", ["share_code"], unique=True)

    op.create_table(
        "fund_report",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_contract_id",
            sa.Integer(),
            sa.ForeignKey("fund_contract.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_type", sa.String(30), nullable=False),
        sa.Column("report_year", sa.Integer(), nullable=False),
        sa.Column("report_quarter", sa.Integer()),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("public_available_at", sa.DateTime(timezone=True)),
        sa.Column("source_provider", sa.String(100), nullable=False),
        sa.Column("source_page_url", sa.Text()),
        sa.Column("document_url", sa.Text()),
        sa.Column("local_document_path", sa.Text()),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("sha256", sa.String(64)),
        sa.Column("parser_version", sa.String(100)),
        sa.Column("parse_status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("parse_confidence", sa.Numeric(5, 4)),
        sa.Column("parse_error", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint(
            "report_quarter IS NULL OR report_quarter BETWEEN 1 AND 4",
            name="ck_fund_report_report_quarter_range",
        ),
        sa.CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="ck_fund_report_parse_confidence_range",
        ),
        sa.UniqueConstraint(
            "fund_contract_id",
            "report_type",
            "report_year",
            "report_quarter",
            name="uq_fund_report_period",
        ),
    )
    op.create_index("ix_fund_report_fund_contract_id", "fund_report", ["fund_contract_id"])
    op.create_index("ix_fund_report_report_type", "fund_report", ["report_type"])
    op.create_index("ix_fund_report_report_year", "fund_report", ["report_year"])
    op.create_index("ix_fund_report_period_end", "fund_report", ["period_end"])
    op.create_index("ix_fund_report_sha256", "fund_report", ["sha256"])
    op.create_index("ix_fund_report_parse_status", "fund_report", ["parse_status"])

    op.create_table(
        "fund_exposure_family",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_contract_id",
            sa.Integer(),
            sa.ForeignKey("fund_contract.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exposure_family_id",
            sa.Integer(),
            sa.ForeignKey("exposure_family.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fund_report_id",
            sa.Integer(),
            sa.ForeignKey("fund_report.id", ondelete="SET NULL"),
        ),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("source_text", sa.Text()),
        *_timestamps(),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_fund_exposure_family_confidence_range",
        ),
        sa.UniqueConstraint(
            "fund_contract_id",
            "exposure_family_id",
            "fund_report_id",
            name="uq_fund_exposure_family_assignment",
        ),
    )
    op.create_index(
        "ix_fund_exposure_family_fund_contract_id",
        "fund_exposure_family",
        ["fund_contract_id"],
    )
    op.create_index(
        "ix_fund_exposure_family_exposure_family_id",
        "fund_exposure_family",
        ["exposure_family_id"],
    )
    op.create_index(
        "ix_fund_exposure_family_fund_report_id",
        "fund_exposure_family",
        ["fund_report_id"],
    )

    _create_report_tables()
    _create_relation_and_market_tables()
    _create_operations_tables()


def _create_report_tables() -> None:
    op.create_table(
        "report_asset_allocation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_report_id",
            sa.Integer(),
            sa.ForeignKey("fund_report.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_name_raw", sa.String(300), nullable=False),
        sa.Column("asset_name_normalized", sa.String(200), nullable=False),
        sa.Column("exposure_basis", sa.String(20), nullable=False, server_default="DIRECT"),
        *_report_row_columns(),
        sa.CheckConstraint(
            "nav_pct IS NULL OR nav_pct >= 0",
            name="ck_report_asset_allocation_nav_pct_nonnegative",
        ),
        sa.CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="ck_report_asset_allocation_parse_confidence_range",
        ),
        sa.UniqueConstraint(
            "fund_report_id",
            "asset_name_normalized",
            "exposure_basis",
            name="uq_report_asset_allocation_row",
        ),
    )
    op.create_index(
        "ix_report_asset_allocation_fund_report_id",
        "report_asset_allocation",
        ["fund_report_id"],
    )

    op.create_table(
        "report_country_allocation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_report_id",
            sa.Integer(),
            sa.ForeignKey("fund_report.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("country_name_raw", sa.String(300), nullable=False),
        sa.Column("country_name_normalized", sa.String(200), nullable=False),
        sa.Column("exposure_basis", sa.String(20), nullable=False, server_default="DIRECT"),
        *_report_row_columns(),
        sa.CheckConstraint(
            "nav_pct IS NULL OR nav_pct >= 0",
            name="ck_report_country_allocation_nav_pct_nonnegative",
        ),
        sa.CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="ck_report_country_allocation_parse_confidence_range",
        ),
        sa.UniqueConstraint(
            "fund_report_id",
            "country_name_normalized",
            "exposure_basis",
            name="uq_report_country_allocation_row",
        ),
    )
    op.create_index(
        "ix_report_country_allocation_fund_report_id",
        "report_country_allocation",
        ["fund_report_id"],
    )
    op.create_index(
        "ix_report_country_allocation_exposure_basis",
        "report_country_allocation",
        ["exposure_basis"],
    )

    op.create_table(
        "report_industry_allocation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_report_id",
            sa.Integer(),
            sa.ForeignKey("fund_report.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("industry_name_raw", sa.String(300), nullable=False),
        sa.Column("industry_name_normalized", sa.String(200), nullable=False),
        sa.Column("exposure_basis", sa.String(20), nullable=False, server_default="DIRECT"),
        *_report_row_columns(),
        sa.CheckConstraint(
            "nav_pct IS NULL OR nav_pct >= 0",
            name="ck_report_industry_allocation_nav_pct_nonnegative",
        ),
        sa.CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="ck_report_industry_allocation_parse_confidence_range",
        ),
        sa.UniqueConstraint(
            "fund_report_id",
            "industry_name_normalized",
            "exposure_basis",
            name="uq_report_industry_allocation_row",
        ),
    )
    op.create_index(
        "ix_report_industry_allocation_fund_report_id",
        "report_industry_allocation",
        ["fund_report_id"],
    )
    op.create_index(
        "ix_report_industry_allocation_exposure_basis",
        "report_industry_allocation",
        ["exposure_basis"],
    )

    op.create_table(
        "report_security_holding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_report_id",
            sa.Integer(),
            sa.ForeignKey("fund_report.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("security_code_raw", sa.String(100)),
        sa.Column("security_name_raw", sa.String(500), nullable=False),
        sa.Column("security_name_normalized", sa.String(300), nullable=False),
        sa.Column("security_name_zh", sa.String(300)),
        sa.Column("security_name_en", sa.String(300)),
        sa.Column("exchange_raw", sa.String(100)),
        sa.Column("market_normalized", sa.String(100)),
        sa.Column("country_normalized", sa.String(100)),
        sa.Column("currency", sa.String(10)),
        sa.Column("quantity", sa.Numeric(28, 8)),
        sa.Column("security_type", sa.String(50), nullable=False),
        sa.Column("exposure_basis", sa.String(20), nullable=False, server_default="DIRECT"),
        *_report_row_columns(),
        sa.CheckConstraint(
            "nav_pct IS NULL OR nav_pct >= 0",
            name="ck_report_security_holding_nav_pct_nonnegative",
        ),
        sa.CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="ck_report_security_holding_parse_confidence_range",
        ),
    )
    op.create_index(
        "ix_report_security_holding_fund_report_id",
        "report_security_holding",
        ["fund_report_id"],
    )
    op.create_index(
        "ix_report_security_holding_market_normalized",
        "report_security_holding",
        ["market_normalized"],
    )
    op.create_index(
        "ix_report_security_holding_country_normalized",
        "report_security_holding",
        ["country_normalized"],
    )
    op.create_index(
        "ix_security_holding_report_basis_rank",
        "report_security_holding",
        ["fund_report_id", "exposure_basis", "rank"],
    )

    op.create_table(
        "report_fund_holding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_report_id",
            sa.Integer(),
            sa.ForeignKey("fund_report.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resolved_fund_contract_id",
            sa.Integer(),
            sa.ForeignKey("fund_contract.id", ondelete="SET NULL"),
        ),
        sa.Column("fund_code_raw", sa.String(100)),
        sa.Column("fund_name_raw", sa.String(500), nullable=False),
        sa.Column("fund_name_normalized", sa.String(300), nullable=False),
        sa.Column("currency", sa.String(10)),
        sa.Column("is_unresolved", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("exposure_basis", sa.String(20), nullable=False, server_default="DIRECT"),
        *_report_row_columns(),
        sa.CheckConstraint(
            "nav_pct IS NULL OR nav_pct >= 0",
            name="ck_report_fund_holding_nav_pct_nonnegative",
        ),
        sa.CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="ck_report_fund_holding_parse_confidence_range",
        ),
        sa.CheckConstraint(
            "resolved_fund_contract_id IS NOT NULL OR is_unresolved = true",
            name="ck_report_fund_holding_resolved_or_unresolved",
        ),
    )
    op.create_index(
        "ix_report_fund_holding_fund_report_id",
        "report_fund_holding",
        ["fund_report_id"],
    )
    op.create_index(
        "ix_report_fund_holding_resolved_fund_contract_id",
        "report_fund_holding",
        ["resolved_fund_contract_id"],
    )
    op.create_index(
        "ix_report_fund_holding_is_unresolved",
        "report_fund_holding",
        ["is_unresolved"],
    )
    op.create_index(
        "ix_fund_holding_report_basis_rank",
        "report_fund_holding",
        ["fund_report_id", "exposure_basis", "rank"],
    )

    op.create_table(
        "report_derived_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_report_id",
            sa.Integer(),
            sa.ForeignKey("fund_report.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tech_scope", sa.String(50), nullable=False, server_default="UNKNOWN"),
        sa.Column("equity_nav_pct", sa.Numeric(14, 8)),
        sa.Column("fund_investment_nav_pct", sa.Numeric(14, 8)),
        sa.Column("cash_and_other_pct", sa.Numeric(14, 8)),
        sa.Column("us_country_pct", sa.Numeric(14, 8)),
        sa.Column("hong_kong_country_pct", sa.Numeric(14, 8)),
        sa.Column("korea_country_pct", sa.Numeric(14, 8)),
        sa.Column("taiwan_country_pct", sa.Numeric(14, 8)),
        sa.Column("information_technology_pct", sa.Numeric(14, 8)),
        sa.Column("communication_services_pct", sa.Numeric(14, 8)),
        sa.Column("semiconductor_top10_pct", sa.Numeric(14, 8)),
        sa.Column("disclosed_top10_pct", sa.Numeric(14, 8)),
        sa.Column("undisclosed_equity_pct", sa.Numeric(14, 8)),
        sa.Column("lookthrough_coverage_pct", sa.Numeric(14, 8)),
        sa.Column("unresolved_fund_weight_pct", sa.Numeric(14, 8)),
        sa.Column("max_lookthrough_depth", sa.Integer()),
        sa.Column(
            "circular_relation_detected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("data_as_of", sa.Date()),
        *_timestamps(),
        sa.CheckConstraint(
            "max_lookthrough_depth IS NULL OR max_lookthrough_depth >= 0",
            name="ck_report_derived_metrics_lookthrough_depth_nonnegative",
        ),
        sa.UniqueConstraint("fund_report_id", name="uq_report_derived_metrics_fund_report_id"),
    )


def _create_relation_and_market_tables() -> None:
    op.create_table(
        "fund_relation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_fund_contract_id",
            sa.Integer(),
            sa.ForeignKey("fund_contract.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_fund_contract_id",
            sa.Integer(),
            sa.ForeignKey("fund_contract.id", ondelete="SET NULL"),
        ),
        sa.Column("external_target_name", sa.String(500)),
        sa.Column("external_target_code", sa.String(100)),
        sa.Column("relation_type", sa.String(50), nullable=False),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column(
            "report_id",
            sa.Integer(),
            sa.ForeignKey("fund_report.id", ondelete="SET NULL"),
        ),
        sa.Column("weight_nav_pct", sa.Numeric(14, 8)),
        sa.Column("source_text", sa.Text()),
        sa.Column("confidence", sa.Numeric(5, 4)),
        *_timestamps(),
        sa.CheckConstraint(
            "target_fund_contract_id IS NOT NULL OR external_target_name IS NOT NULL "
            "OR external_target_code IS NOT NULL",
            name="ck_fund_relation_target_present",
        ),
        sa.CheckConstraint(
            "weight_nav_pct IS NULL OR weight_nav_pct >= 0",
            name="ck_fund_relation_weight_nonnegative",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_fund_relation_confidence_range",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="ck_fund_relation_effective_date_order",
        ),
    )
    op.create_index(
        "ix_fund_relation_target_fund_contract_id",
        "fund_relation",
        ["target_fund_contract_id"],
    )
    op.create_index("ix_fund_relation_report_id", "fund_relation", ["report_id"])
    op.create_index(
        "ix_fund_relation_source_type",
        "fund_relation",
        ["source_fund_contract_id", "relation_type"],
    )

    op.create_table(
        "daily_fund_nav",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_share_id",
            sa.Integer(),
            sa.ForeignKey("fund_share.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("unit_nav", sa.Numeric(24, 8), nullable=False),
        sa.Column("accumulated_nav", sa.Numeric(24, 8)),
        sa.Column("published_daily_return_pct", sa.Numeric(14, 8)),
        sa.Column("calculated_daily_return_pct", sa.Numeric(14, 8)),
        sa.Column("source_provider", sa.String(100), nullable=False),
        sa.Column("source_published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("raw_payload_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("unit_nav > 0", name="ck_daily_fund_nav_unit_nav_positive"),
        sa.CheckConstraint(
            "accumulated_nav IS NULL OR accumulated_nav > 0",
            name="ck_daily_fund_nav_accumulated_nav_positive",
        ),
        sa.UniqueConstraint(
            "fund_share_id",
            "nav_date",
            "source_provider",
            name="uq_daily_fund_nav_source",
        ),
    )
    op.create_index("ix_daily_fund_nav_fund_share_id", "daily_fund_nav", ["fund_share_id"])
    op.create_index("ix_daily_fund_nav_nav_date", "daily_fund_nav", ["nav_date"])

    op.create_table(
        "daily_exchange_price",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fund_share_id",
            sa.Integer(),
            sa.ForeignKey("fund_share.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(24, 8), nullable=False),
        sa.Column("high", sa.Numeric(24, 8), nullable=False),
        sa.Column("low", sa.Numeric(24, 8), nullable=False),
        sa.Column("close", sa.Numeric(24, 8), nullable=False),
        sa.Column("pct_change", sa.Numeric(14, 8)),
        sa.Column("volume", sa.Numeric(28, 8)),
        sa.Column("turnover", sa.Numeric(24, 6)),
        sa.Column("premium_discount_pct", sa.Numeric(14, 8)),
        sa.Column("corresponding_nav_date", sa.Date()),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("source_provider", sa.String(100), nullable=False),
        sa.CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0",
            name="ck_daily_exchange_price_ohlc_positive",
        ),
        sa.CheckConstraint("high >= low", name="ck_daily_exchange_price_high_not_below_low"),
        sa.CheckConstraint(
            "volume IS NULL OR volume >= 0",
            name="ck_daily_exchange_price_volume_nonnegative",
        ),
        sa.CheckConstraint(
            "turnover IS NULL OR turnover >= 0",
            name="ck_daily_exchange_price_turnover_nonnegative",
        ),
        sa.UniqueConstraint(
            "fund_share_id",
            "trade_date",
            "source_provider",
            name="uq_daily_exchange_price_source",
        ),
    )
    op.create_index(
        "ix_daily_exchange_price_fund_share_id",
        "daily_exchange_price",
        ["fund_share_id"],
    )
    op.create_index("ix_daily_exchange_price_trade_date", "daily_exchange_price", ["trade_date"])


def _create_operations_tables() -> None:
    op.create_table(
        "source_artifact",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "ingestion_run_id",
            sa.Integer(),
            sa.ForeignKey("ingestion_run.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "fund_contract_id",
            sa.Integer(),
            sa.ForeignKey("fund_contract.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "fund_report_id",
            sa.Integer(),
            sa.ForeignKey("fund_report.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "fund_share_id",
            sa.Integer(),
            sa.ForeignKey("fund_share.id", ondelete="SET NULL"),
        ),
        sa.Column("artifact_type", sa.String(50), nullable=False),
        sa.Column("source_provider", sa.String(100), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(100)),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer()),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("source_provider", "sha256", name="uq_source_artifact_provider_hash"),
    )
    for column in (
        "ingestion_run_id",
        "fund_contract_id",
        "fund_report_id",
        "fund_share_id",
        "sha256",
    ):
        op.create_index(f"ix_source_artifact_{column}", "source_artifact", [column])

    op.create_table(
        "data_quality_issue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "ingestion_run_id",
            sa.Integer(),
            sa.ForeignKey("ingestion_run.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "fund_contract_id",
            sa.Integer(),
            sa.ForeignKey("fund_contract.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "fund_report_id",
            sa.Integer(),
            sa.ForeignKey("fund_report.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "fund_share_id",
            sa.Integer(),
            sa.ForeignKey("fund_share.id", ondelete="CASCADE"),
        ),
        sa.Column("issue_code", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "fund_contract_id IS NOT NULL OR fund_report_id IS NOT NULL "
            "OR fund_share_id IS NOT NULL OR ingestion_run_id IS NOT NULL",
            name="ck_data_quality_issue_issue_has_context",
        ),
    )
    for column in (
        "ingestion_run_id",
        "fund_contract_id",
        "fund_report_id",
        "fund_share_id",
        "issue_code",
        "severity",
        "status",
    ):
        op.create_index(f"ix_data_quality_issue_{column}", "data_quality_issue", [column])
    op.create_index("ix_data_quality_issue_detected_at", "data_quality_issue", ["detected_at"])
    op.create_index(
        "ix_data_quality_issue_status_severity",
        "data_quality_issue",
        ["status", "severity"],
    )


def downgrade() -> None:
    for table_name in (
        "data_quality_issue",
        "source_artifact",
        "daily_exchange_price",
        "daily_fund_nav",
        "fund_relation",
        "report_derived_metrics",
        "report_fund_holding",
        "report_security_holding",
        "report_industry_allocation",
        "report_country_allocation",
        "report_asset_allocation",
        "fund_exposure_family",
        "fund_report",
        "fund_share",
        "ingestion_run",
        "exposure_family",
        "fund_contract",
    ):
        op.drop_table(table_name)
