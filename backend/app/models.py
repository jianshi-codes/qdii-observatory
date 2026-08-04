"""SQLAlchemy 2 domain model for contracts, reports, exposures, and prices."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base

MONEY = Numeric(24, 6)
PERCENT = Numeric(14, 8)
PRICE = Numeric(24, 8)
QUANTITY = Numeric(28, 8)
FX_RATE = Numeric(24, 12)
CONFIDENCE = Numeric(5, 4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class FundContract(TimestampMixin, Base):
    __tablename__ = "fund_contract"
    __table_args__ = (
        CheckConstraint(
            "length(representative_code) = 6",
            name="representative_code_length",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(300), nullable=False)
    manager_name: Mapped[str] = mapped_column(String(200), nullable=False)
    region: Mapped[str | None] = mapped_column(String(100), index=True)
    representative_code: Mapped[str] = mapped_column(
        String(6), nullable=False, unique=True, index=True
    )
    strategy_type: Mapped[str | None] = mapped_column(String(100))
    original_category: Mapped[str | None] = mapped_column(String(100), index=True)
    wrapper_type: Mapped[str | None] = mapped_column(String(50), index=True)
    tech_scope: Mapped[str] = mapped_column(
        String(50), nullable=False, default="UNKNOWN", server_default="UNKNOWN", index=True
    )
    is_user_selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", index=True
    )
    is_dependency: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )

    shares: Mapped[list[FundShare]] = relationship(
        back_populates="fund_contract", cascade="all, delete-orphan"
    )
    reports: Mapped[list[FundReport]] = relationship(
        back_populates="fund_contract", cascade="all, delete-orphan"
    )
    exposure_families: Mapped[list[FundExposureFamily]] = relationship(
        back_populates="fund_contract", cascade="all, delete-orphan"
    )


class FundShare(TimestampMixin, Base):
    __tablename__ = "fund_share"
    __table_args__ = (CheckConstraint("length(share_code) = 6", name="share_code_length"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_contract_id: Mapped[int] = mapped_column(
        ForeignKey("fund_contract.id", ondelete="CASCADE"), nullable=False, index=True
    )
    share_code: Mapped[str] = mapped_column(String(6), nullable=False, unique=True, index=True)
    share_class: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str] = mapped_column(
        String(10), nullable=False, default="CNY", server_default="CNY"
    )
    is_exchange_traded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    exchange: Mapped[str | None] = mapped_column(String(30))

    fund_contract: Mapped[FundContract] = relationship(back_populates="shares")
    nav_rows: Mapped[list[DailyFundNav]] = relationship(
        back_populates="fund_share", cascade="all, delete-orphan"
    )
    exchange_prices: Mapped[list[DailyExchangePrice]] = relationship(
        back_populates="fund_share", cascade="all, delete-orphan"
    )
    purchase_limits: Mapped[list[DailyPurchaseLimit]] = relationship(
        back_populates="fund_share", cascade="all, delete-orphan"
    )
    fee_snapshots: Mapped[list[DailyFundFee]] = relationship(
        back_populates="fund_share", cascade="all, delete-orphan"
    )
    portfolio_positions: Mapped[list[PortfolioPosition]] = relationship(
        back_populates="fund_share", cascade="all, delete-orphan"
    )


class ExposureFamily(TimestampMixin, Base):
    __tablename__ = "exposure_family"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    funds: Mapped[list[FundExposureFamily]] = relationship(
        back_populates="exposure_family", cascade="all, delete-orphan"
    )


class FundExposureFamily(TimestampMixin, Base):
    __tablename__ = "fund_exposure_family"
    __table_args__ = (
        UniqueConstraint(
            "fund_contract_id",
            "exposure_family_id",
            "fund_report_id",
            name="uq_fund_exposure_family_assignment",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_contract_id: Mapped[int] = mapped_column(
        ForeignKey("fund_contract.id", ondelete="CASCADE"), nullable=False, index=True
    )
    exposure_family_id: Mapped[int] = mapped_column(
        ForeignKey("exposure_family.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fund_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("fund_report.id", ondelete="SET NULL"), index=True
    )
    confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)
    source_text: Mapped[str | None] = mapped_column(Text)

    fund_contract: Mapped[FundContract] = relationship(back_populates="exposure_families")
    exposure_family: Mapped[ExposureFamily] = relationship(back_populates="funds")
    fund_report: Mapped[FundReport | None] = relationship()


class FundReport(TimestampMixin, Base):
    __tablename__ = "fund_report"
    __table_args__ = (
        UniqueConstraint(
            "fund_contract_id",
            "report_type",
            "report_year",
            "report_quarter",
            name="uq_fund_report_period",
        ),
        CheckConstraint(
            "report_quarter IS NULL OR report_quarter BETWEEN 1 AND 4",
            name="report_quarter_range",
        ),
        CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="parse_confidence_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_contract_id: Mapped[int] = mapped_column(
        ForeignKey("fund_contract.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    report_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    report_quarter: Mapped[int | None] = mapped_column(Integer)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    public_available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    source_page_url: Mapped[str | None] = mapped_column(Text)
    document_url: Mapped[str | None] = mapped_column(Text)
    local_document_path: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    parser_version: Mapped[str | None] = mapped_column(String(100))
    parse_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING", server_default="PENDING", index=True
    )
    parse_confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)
    parse_error: Mapped[str | None] = mapped_column(Text)

    fund_contract: Mapped[FundContract] = relationship(back_populates="reports")
    asset_allocations: Mapped[list[ReportAssetAllocation]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    country_allocations: Mapped[list[ReportCountryAllocation]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    industry_allocations: Mapped[list[ReportIndustryAllocation]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    security_holdings: Mapped[list[ReportSecurityHolding]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    fund_holdings: Mapped[list[ReportFundHolding]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )
    derived_metrics: Mapped[ReportDerivedMetrics | None] = relationship(
        back_populates="report", cascade="all, delete-orphan", uselist=False
    )


class ReportRowMixin:
    fair_value_cny: Mapped[Decimal | None] = mapped_column(MONEY)
    nav_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    rank: Mapped[int | None] = mapped_column(Integer)
    source_section: Mapped[str] = mapped_column(String(300), nullable=False)
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    parse_confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)


class ReportAssetAllocation(ReportRowMixin, Base):
    __tablename__ = "report_asset_allocation"
    __table_args__ = (
        CheckConstraint("nav_pct IS NULL OR nav_pct >= 0", name="nav_pct_nonnegative"),
        CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="parse_confidence_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_report_id: Mapped[int] = mapped_column(
        ForeignKey("fund_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_name_raw: Mapped[str] = mapped_column(String(300), nullable=False)
    asset_name_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    exposure_basis: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DIRECT", server_default="DIRECT"
    )

    report: Mapped[FundReport] = relationship(back_populates="asset_allocations")


class ReportCountryAllocation(ReportRowMixin, Base):
    __tablename__ = "report_country_allocation"
    __table_args__ = (
        CheckConstraint("nav_pct IS NULL OR nav_pct >= 0", name="nav_pct_nonnegative"),
        CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="parse_confidence_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_report_id: Mapped[int] = mapped_column(
        ForeignKey("fund_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    country_name_raw: Mapped[str] = mapped_column(String(300), nullable=False)
    country_name_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    exposure_basis: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DIRECT", server_default="DIRECT", index=True
    )

    report: Mapped[FundReport] = relationship(back_populates="country_allocations")


class ReportIndustryAllocation(ReportRowMixin, Base):
    __tablename__ = "report_industry_allocation"
    __table_args__ = (
        CheckConstraint("nav_pct IS NULL OR nav_pct >= 0", name="nav_pct_nonnegative"),
        CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="parse_confidence_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_report_id: Mapped[int] = mapped_column(
        ForeignKey("fund_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    industry_name_raw: Mapped[str] = mapped_column(String(300), nullable=False)
    industry_name_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    exposure_basis: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DIRECT", server_default="DIRECT", index=True
    )

    report: Mapped[FundReport] = relationship(back_populates="industry_allocations")


class ReportSecurityHolding(ReportRowMixin, Base):
    __tablename__ = "report_security_holding"
    __table_args__ = (
        CheckConstraint("nav_pct IS NULL OR nav_pct >= 0", name="nav_pct_nonnegative"),
        CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="parse_confidence_range",
        ),
        Index(
            "ix_security_holding_report_basis_rank",
            "fund_report_id",
            "exposure_basis",
            "rank",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_report_id: Mapped[int] = mapped_column(
        ForeignKey("fund_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    security_code_raw: Mapped[str | None] = mapped_column(String(100))
    security_name_raw: Mapped[str] = mapped_column(String(500), nullable=False)
    security_name_normalized: Mapped[str] = mapped_column(String(300), nullable=False)
    security_name_zh: Mapped[str | None] = mapped_column(String(300))
    security_name_en: Mapped[str | None] = mapped_column(String(300))
    exchange_raw: Mapped[str | None] = mapped_column(String(100))
    market_normalized: Mapped[str | None] = mapped_column(String(100), index=True)
    country_normalized: Mapped[str | None] = mapped_column(String(100), index=True)
    currency: Mapped[str | None] = mapped_column(String(10))
    quantity: Mapped[Decimal | None] = mapped_column(QUANTITY)
    security_type: Mapped[str] = mapped_column(String(50), nullable=False)
    exposure_basis: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DIRECT", server_default="DIRECT"
    )

    report: Mapped[FundReport] = relationship(back_populates="security_holdings")


class ReportFundHolding(ReportRowMixin, Base):
    __tablename__ = "report_fund_holding"
    __table_args__ = (
        CheckConstraint("nav_pct IS NULL OR nav_pct >= 0", name="nav_pct_nonnegative"),
        CheckConstraint(
            "parse_confidence IS NULL OR (parse_confidence >= 0 AND parse_confidence <= 1)",
            name="parse_confidence_range",
        ),
        CheckConstraint(
            "resolved_fund_contract_id IS NOT NULL OR is_unresolved = true",
            name="resolved_or_unresolved",
        ),
        Index(
            "ix_fund_holding_report_basis_rank",
            "fund_report_id",
            "exposure_basis",
            "rank",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_report_id: Mapped[int] = mapped_column(
        ForeignKey("fund_report.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resolved_fund_contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("fund_contract.id", ondelete="SET NULL"), index=True
    )
    fund_code_raw: Mapped[str | None] = mapped_column(String(100))
    fund_name_raw: Mapped[str] = mapped_column(String(500), nullable=False)
    fund_name_normalized: Mapped[str] = mapped_column(String(300), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(10))
    is_unresolved: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", index=True
    )
    exposure_basis: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DIRECT", server_default="DIRECT"
    )

    report: Mapped[FundReport] = relationship(back_populates="fund_holdings")
    resolved_fund_contract: Mapped[FundContract | None] = relationship()


class FundRelation(TimestampMixin, Base):
    __tablename__ = "fund_relation"
    __table_args__ = (
        CheckConstraint(
            "target_fund_contract_id IS NOT NULL OR external_target_name IS NOT NULL "
            "OR external_target_code IS NOT NULL",
            name="target_present",
        ),
        CheckConstraint("weight_nav_pct IS NULL OR weight_nav_pct >= 0", name="weight_nonnegative"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="effective_date_order",
        ),
        Index("ix_fund_relation_source_type", "source_fund_contract_id", "relation_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_fund_contract_id: Mapped[int] = mapped_column(
        ForeignKey("fund_contract.id", ondelete="CASCADE"), nullable=False
    )
    target_fund_contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("fund_contract.id", ondelete="SET NULL"), index=True
    )
    external_target_name: Mapped[str | None] = mapped_column(String(500))
    external_target_code: Mapped[str | None] = mapped_column(String(100))
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("fund_report.id", ondelete="SET NULL"), index=True
    )
    weight_nav_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    source_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)

    source_fund_contract: Mapped[FundContract] = relationship(
        foreign_keys=[source_fund_contract_id]
    )
    target_fund_contract: Mapped[FundContract | None] = relationship(
        foreign_keys=[target_fund_contract_id]
    )
    report: Mapped[FundReport | None] = relationship()


class ReportDerivedMetrics(TimestampMixin, Base):
    __tablename__ = "report_derived_metrics"
    __table_args__ = (
        CheckConstraint(
            "max_lookthrough_depth IS NULL OR max_lookthrough_depth >= 0",
            name="lookthrough_depth_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_report_id: Mapped[int] = mapped_column(
        ForeignKey("fund_report.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    tech_scope: Mapped[str] = mapped_column(
        String(50), nullable=False, default="UNKNOWN", server_default="UNKNOWN"
    )
    equity_nav_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    fund_investment_nav_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    cash_and_other_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    us_country_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    hong_kong_country_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    korea_country_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    taiwan_country_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    information_technology_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    communication_services_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    semiconductor_top10_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    disclosed_top10_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    undisclosed_equity_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    lookthrough_coverage_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    unresolved_fund_weight_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    max_lookthrough_depth: Mapped[int | None] = mapped_column(Integer)
    circular_relation_detected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    data_as_of: Mapped[date | None] = mapped_column(Date)

    report: Mapped[FundReport] = relationship(back_populates="derived_metrics")


class DailyFundNav(Base):
    __tablename__ = "daily_fund_nav"
    __table_args__ = (
        UniqueConstraint(
            "fund_share_id", "nav_date", "source_provider", name="uq_daily_fund_nav_source"
        ),
        CheckConstraint("unit_nav > 0", name="unit_nav_positive"),
        CheckConstraint(
            "accumulated_nav IS NULL OR accumulated_nav > 0",
            name="accumulated_nav_positive",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_share_id: Mapped[int] = mapped_column(
        ForeignKey("fund_share.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nav_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    unit_nav: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    accumulated_nav: Mapped[Decimal | None] = mapped_column(PRICE)
    published_daily_return_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    calculated_daily_return_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    source_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    fund_share: Mapped[FundShare] = relationship(back_populates="nav_rows")


class DailyExchangePrice(Base):
    __tablename__ = "daily_exchange_price"
    __table_args__ = (
        UniqueConstraint(
            "fund_share_id",
            "trade_date",
            "source_provider",
            name="uq_daily_exchange_price_source",
        ),
        CheckConstraint("open > 0 AND high > 0 AND low > 0 AND close > 0", name="ohlc_positive"),
        CheckConstraint("high >= low", name="high_not_below_low"),
        CheckConstraint("volume IS NULL OR volume >= 0", name="volume_nonnegative"),
        CheckConstraint("turnover IS NULL OR turnover >= 0", name="turnover_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_share_id: Mapped[int] = mapped_column(
        ForeignKey("fund_share.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    open: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    high: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    low: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    close: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    pct_change: Mapped[Decimal | None] = mapped_column(PERCENT)
    volume: Mapped[Decimal | None] = mapped_column(QUANTITY)
    turnover: Mapped[Decimal | None] = mapped_column(MONEY)
    premium_discount_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    corresponding_nav_date: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_provider: Mapped[str] = mapped_column(String(100), nullable=False)

    fund_share: Mapped[FundShare] = relationship(back_populates="exchange_prices")


class DailyPurchaseLimit(Base):
    """Source-specific daily sales-channel availability and purchase caps."""

    __tablename__ = "daily_purchase_limit"
    __table_args__ = (
        UniqueConstraint(
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
        CheckConstraint(
            "channel_type IN ('DIRECT', 'DISTRIBUTION')",
            name="channel_type_allowed",
        ),
        CheckConstraint(
            "length(trim(channel_key)) > 0",
            name="channel_key_nonempty",
        ),
        CheckConstraint(
            "length(trim(channel_name)) > 0",
            name="channel_name_nonempty",
        ),
        CheckConstraint(
            "business_type IN ('PURCHASE', 'RECURRING_INVESTMENT', 'CONVERSION_IN')",
            name="business_type_allowed",
        ),
        CheckConstraint(
            "availability_state IN ('OPEN', 'PAUSED', 'UNKNOWN', 'NOT_SOLD', 'NOT_APPLICABLE')",
            name="availability_state_allowed",
        ),
        CheckConstraint(
            "cap_state IN ('LIMITED', 'UNLIMITED', 'UNKNOWN')",
            name="cap_state_allowed",
        ),
        CheckConstraint(
            "limit_basis IN ('PER_ACCOUNT_PER_DAY', 'UNKNOWN')",
            name="limit_basis_allowed",
        ),
        CheckConstraint(
            "share_scope IN ('PER_SHARE', 'ALL_SHARES_COMBINED', 'UNKNOWN')",
            name="share_scope_allowed",
        ),
        CheckConstraint(
            "(cap_state = 'LIMITED' AND daily_limit_amount IS NOT NULL "
            "AND daily_limit_amount > 0) OR "
            "(cap_state IN ('UNLIMITED', 'UNKNOWN') AND daily_limit_amount IS NULL)",
            name="amount_matches_cap_state",
        ),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_format",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="effective_date_order",
        ),
        CheckConstraint(
            "length(trim(source_provider)) > 0",
            name="source_provider_nonempty",
        ),
        CheckConstraint(
            "length(trim(source_url)) > 0",
            name="source_url_nonempty",
        ),
        CheckConstraint(
            "length(raw_payload_hash) = 64",
            name="raw_payload_hash_length",
        ),
        CheckConstraint(
            "length(trim(raw_text)) > 0",
            name="raw_text_nonempty",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        Index(
            "ix_daily_purchase_limit_share_snapshot",
            "fund_share_id",
            "snapshot_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_share_id: Mapped[int] = mapped_column(
        ForeignKey("fund_share.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    channel_key: Mapped[str] = mapped_column(String(100), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(200), nullable=False)
    business_type: Mapped[str] = mapped_column(String(40), nullable=False)
    availability_state: Mapped[str] = mapped_column(String(30), nullable=False)
    cap_state: Mapped[str] = mapped_column(String(20), nullable=False)
    daily_limit_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="CNY", server_default="CNY"
    )
    limit_basis: Mapped[str] = mapped_column(String(50), nullable=False)
    share_scope: Mapped[str] = mapped_column(String(50), nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_artifact_id: Mapped[int] = mapped_column(
        ForeignKey("source_artifact.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    raw_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)

    fund_share: Mapped[FundShare] = relationship(back_populates="purchase_limits")
    source_artifact: Mapped[SourceArtifact] = relationship()


class DailyFundFee(Base):
    """Observed fund-share fee schedule; operating fees are already reflected in NAV."""

    __tablename__ = "daily_fund_fee"
    __table_args__ = (
        UniqueConstraint(
            "fund_share_id",
            "snapshot_date",
            "source_provider",
            name="uq_daily_fund_fee_identity",
        ),
        CheckConstraint(
            "management_fee_pct_annual IS NULL OR management_fee_pct_annual BETWEEN 0 AND 100",
            name="management_fee_range",
        ),
        CheckConstraint(
            "custody_fee_pct_annual IS NULL OR custody_fee_pct_annual BETWEEN 0 AND 100",
            name="custody_fee_range",
        ),
        CheckConstraint(
            "sales_service_fee_pct_annual IS NULL OR "
            "sales_service_fee_pct_annual BETWEEN 0 AND 100",
            name="sales_service_fee_range",
        ),
        CheckConstraint(
            "standard_purchase_fee_pct IS NULL OR standard_purchase_fee_pct BETWEEN 0 AND 100",
            name="standard_purchase_fee_range",
        ),
        CheckConstraint(
            "discounted_purchase_fee_pct IS NULL OR discounted_purchase_fee_pct BETWEEN 0 AND 100",
            name="discounted_purchase_fee_range",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="confidence_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_share_id: Mapped[int] = mapped_column(
        ForeignKey("fund_share.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    management_fee_pct_annual: Mapped[Decimal | None] = mapped_column(PERCENT)
    custody_fee_pct_annual: Mapped[Decimal | None] = mapped_column(PERCENT)
    sales_service_fee_pct_annual: Mapped[Decimal | None] = mapped_column(PERCENT)
    standard_purchase_fee_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    discounted_purchase_fee_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    source_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_artifact_id: Mapped[int] = mapped_column(
        ForeignKey("source_artifact.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    raw_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)

    fund_share: Mapped[FundShare] = relationship(back_populates="fee_snapshots")
    source_artifact: Mapped[SourceArtifact] = relationship()


class PortfolioPosition(TimestampMixin, Base):
    """User-maintained position snapshot anchored to an archived share NAV."""

    __tablename__ = "portfolio_position"
    __table_args__ = (
        UniqueConstraint("platform", "fund_share_id", name="uq_portfolio_position_platform_share"),
        CheckConstraint("length(trim(platform)) > 0", name="platform_nonempty"),
        CheckConstraint("reported_units > 0", name="reported_units_positive"),
        CheckConstraint("reported_market_value > 0", name="market_value_positive"),
        CheckConstraint("anchor_unit_nav > 0", name="anchor_unit_nav_positive"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_format",
        ),
        CheckConstraint(
            "recurring_frequency IS NULL OR recurring_frequency = 'DAILY'",
            name="recurring_frequency_allowed",
        ),
        CheckConstraint(
            "recurring_gross_amount IS NULL OR recurring_gross_amount > 0",
            name="recurring_gross_amount_positive",
        ),
        CheckConstraint(
            "recurring_fee_pct IS NULL OR recurring_fee_pct BETWEEN 0 AND 100",
            name="recurring_fee_range",
        ),
        CheckConstraint(
            "recurring_net_amount IS NULL OR recurring_net_amount > 0",
            name="recurring_net_amount_positive",
        ),
        CheckConstraint(
            "recurring_confirmation_lag_days BETWEEN 0 AND 10",
            name="recurring_confirmation_lag_days_range",
        ),
        CheckConstraint(
            "manual_purchase_fee_pct IS NULL OR manual_purchase_fee_pct BETWEEN 0 AND 100",
            name="manual_purchase_fee_range",
        ),
        CheckConstraint(
            "manual_management_fee_pct_annual IS NULL OR "
            "manual_management_fee_pct_annual BETWEEN 0 AND 100",
            name="manual_management_fee_range",
        ),
        CheckConstraint(
            "manual_custody_fee_pct_annual IS NULL OR "
            "manual_custody_fee_pct_annual BETWEEN 0 AND 100",
            name="manual_custody_fee_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fund_share_id: Mapped[int] = mapped_column(
        ForeignKey("fund_share.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reported_units: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    reported_market_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reported_profit_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reported_return_pct: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)
    reported_cumulative_profit_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    anchor_nav_date: Mapped[date] = mapped_column(Date, nullable=False)
    anchor_unit_nav: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    recurring_frequency: Mapped[str | None] = mapped_column(String(20))
    recurring_gross_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    recurring_fee_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    recurring_net_amount: Mapped[Decimal | None] = mapped_column(MONEY)
    recurring_confirmation_lag_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default="2"
    )
    manual_purchase_fee_pct: Mapped[Decimal | None] = mapped_column(PERCENT)
    manual_management_fee_pct_annual: Mapped[Decimal | None] = mapped_column(PERCENT)
    manual_custody_fee_pct_annual: Mapped[Decimal | None] = mapped_column(PERCENT)
    source_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="USER_REPORTED", server_default="USER_REPORTED"
    )
    data_quality_note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", index=True
    )

    fund_share: Mapped[FundShare] = relationship(back_populates="portfolio_positions")
    cash_flows: Mapped[list[PortfolioCashFlow]] = relationship(
        back_populates="portfolio_position", cascade="all, delete-orphan"
    )
    recurring_executions: Mapped[list[PortfolioRecurringExecution]] = relationship(
        back_populates="portfolio_position", cascade="all, delete-orphan"
    )
    recurring_orders: Mapped[list[PortfolioRecurringOrder]] = relationship(
        back_populates="portfolio_position", cascade="all, delete-orphan"
    )


class PortfolioCashFlow(TimestampMixin, Base):
    """User-reported realized portfolio cash flow such as a cash dividend."""

    __tablename__ = "portfolio_cash_flow"
    __table_args__ = (
        CheckConstraint("flow_type = 'DIVIDEND'", name="flow_type_allowed"),
        CheckConstraint("occurred_year BETWEEN 2000 AND 2100", name="occurred_year_range"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="currency_format",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_position_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_position.id", ondelete="CASCADE"), nullable=False, index=True
    )
    flow_type: Mapped[str] = mapped_column(String(30), nullable=False)
    occurred_on: Mapped[date | None] = mapped_column(Date)
    occurred_year: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="USER_REPORTED", server_default="USER_REPORTED"
    )
    note: Mapped[str | None] = mapped_column(Text)

    portfolio_position: Mapped[PortfolioPosition] = relationship(back_populates="cash_flows")


class PortfolioRecurringExecution(TimestampMixin, Base):
    """One idempotent recurring investment settled at a source-backed NAV."""

    __tablename__ = "portfolio_recurring_execution"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_position_id",
            "nav_date",
            name="uq_portfolio_recurring_execution_position_nav_date",
        ),
        CheckConstraint("unit_nav > 0", name="unit_nav_positive"),
        CheckConstraint("gross_amount > 0", name="gross_amount_positive"),
        CheckConstraint("fee_pct BETWEEN 0 AND 100", name="fee_range"),
        CheckConstraint("net_amount > 0", name="net_amount_positive"),
        CheckConstraint("units > 0", name="units_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_position_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_position.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nav_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    unit_nav: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee_pct: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    units: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    source_provider: Mapped[str] = mapped_column(String(100), nullable=False)

    portfolio_position: Mapped[PortfolioPosition] = relationship(
        back_populates="recurring_executions"
    )


class PortfolioRecurringOrder(TimestampMixin, Base):
    """A user-triggered recurring order waiting for its source-backed valuation NAV."""

    __tablename__ = "portfolio_recurring_order"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_position_id",
            "order_date",
            name="uq_portfolio_recurring_order_position_order_date",
        ),
        UniqueConstraint(
            "settled_execution_id",
            name="uq_portfolio_recurring_order_settled_execution",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'SETTLED')",
            name="status_allowed",
        ),
        CheckConstraint("gross_amount > 0", name="gross_amount_positive"),
        CheckConstraint("fee_pct BETWEEN 0 AND 100", name="fee_range"),
        CheckConstraint("net_amount > 0", name="net_amount_positive"),
        CheckConstraint(
            "expected_confirmation_date >= order_date",
            name="expected_confirmation_not_before_order",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND settled_execution_id IS NULL AND confirmed_at IS NULL) OR "
            "(status = 'SETTLED' AND settled_execution_id IS NOT NULL "
            "AND confirmed_at IS NOT NULL)",
            name="settlement_state_complete",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_position_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio_position.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    expected_confirmation_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING", server_default="PENDING", index=True
    )
    gross_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee_pct: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    settled_execution_id: Mapped[int | None] = mapped_column(
        ForeignKey("portfolio_recurring_execution.id", ondelete="SET NULL"), index=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    portfolio_position: Mapped[PortfolioPosition] = relationship(
        back_populates="recurring_orders"
    )
    settled_execution: Mapped[PortfolioRecurringExecution | None] = relationship()


class DailyExchangeRate(Base):
    """Source-backed daily conversion rate, quoted as target units per base unit."""

    __tablename__ = "daily_exchange_rate"
    __table_args__ = (
        UniqueConstraint(
            "base_currency",
            "quote_currency",
            "rate_date",
            "source_provider",
            name="uq_daily_exchange_rate_identity",
        ),
        CheckConstraint("base_currency <> quote_currency", name="currencies_differ"),
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="confidence_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False, index=True)
    rate_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    rate: Mapped[Decimal] = mapped_column(FX_RATE, nullable=False)
    source_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_artifact_id: Mapped[int] = mapped_column(
        ForeignKey("source_artifact.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    raw_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(CONFIDENCE)

    source_artifact: Mapped[SourceArtifact] = relationship()


class IngestionRun(Base):
    __tablename__ = "ingestion_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records_seen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    records_written: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    records_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error_message: Mapped[str | None] = mapped_column(Text)


class DataOperation(TimestampMixin, Base):
    """One durable user-requested data operation executed by the worker service."""

    __tablename__ = "data_operation"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('prepare', 'sync-daily', 'sync-sales-limits', "
            "'sync-reports', 'parse-reports')",
            name="operation_allowed",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint(
            "(status IN ('queued', 'running') AND active_slot = 1) OR "
            "(status IN ('succeeded', 'partial', 'failed') AND active_slot IS NULL)",
            name="active_slot_matches_status",
        ),
        CheckConstraint("lookback_days BETWEEN 1 AND 100", name="lookback_days_range"),
        CheckConstraint(
            "report_quarter IS NULL OR report_quarter BETWEEN 1 AND 4",
            name="report_quarter_range",
        ),
        CheckConstraint(
            "stage_completed >= 0 AND stage_total >= 1 AND stage_completed <= stage_total",
            name="stage_progress_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    active_slot: Mapped[int | None] = mapped_column(Integer, unique=True)
    fund_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    report_year: Mapped[int | None] = mapped_column(Integer)
    report_quarter: Mapped[int | None] = mapped_column(Integer)
    current_stage: Mapped[str | None] = mapped_column(String(50))
    stage_completed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    stage_total: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    run_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    records_written: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    records_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    recurring_orders_created: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    recurring_orders_settled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    recurring_executions_written: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    recurring_positions_updated: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    recurring_latest_nav_date: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class SourceArtifact(TimestampMixin, Base):
    __tablename__ = "source_artifact"
    __table_args__ = (
        UniqueConstraint("source_provider", "sha256", name="uq_source_artifact_provider_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingestion_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_run.id", ondelete="SET NULL"), index=True
    )
    fund_contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("fund_contract.id", ondelete="SET NULL"), index=True
    )
    fund_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("fund_report.id", ondelete="SET NULL"), index=True
    )
    fund_share_id: Mapped[int | None] = mapped_column(
        ForeignKey("fund_share.id", ondelete="SET NULL"), index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    byte_size: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class DataQualityIssue(TimestampMixin, Base):
    __tablename__ = "data_quality_issue"
    __table_args__ = (
        CheckConstraint(
            "fund_contract_id IS NOT NULL OR fund_report_id IS NOT NULL "
            "OR fund_share_id IS NOT NULL OR ingestion_run_id IS NOT NULL",
            name="issue_has_context",
        ),
        Index("ix_data_quality_issue_status_severity", "status", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingestion_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingestion_run.id", ondelete="SET NULL"), index=True
    )
    fund_contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("fund_contract.id", ondelete="CASCADE"), index=True
    )
    fund_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("fund_report.id", ondelete="CASCADE"), index=True
    )
    fund_share_id: Mapped[int | None] = mapped_column(
        ForeignKey("fund_share.id", ondelete="CASCADE"), index=True
    )
    issue_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="OPEN", server_default="OPEN", index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
