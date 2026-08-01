"""Explicit Pydantic response contracts for the local API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DerivedMetricsRead(ApiModel):
    tech_scope: str
    equity_nav_pct: Decimal | None
    fund_investment_nav_pct: Decimal | None
    cash_and_other_pct: Decimal | None
    us_country_pct: Decimal | None
    hong_kong_country_pct: Decimal | None
    korea_country_pct: Decimal | None
    taiwan_country_pct: Decimal | None
    information_technology_pct: Decimal | None
    communication_services_pct: Decimal | None
    semiconductor_top10_pct: Decimal | None
    disclosed_top10_pct: Decimal | None
    undisclosed_equity_pct: Decimal | None
    lookthrough_coverage_pct: Decimal | None
    unresolved_fund_weight_pct: Decimal | None
    max_lookthrough_depth: int | None
    circular_relation_detected: bool
    data_as_of: date | None


class PurchaseLimitSummaryRead(ApiModel):
    snapshot_date: date
    channel_type: Literal["DIRECT", "DISTRIBUTION"]
    channel_key: str
    channel_name: str
    availability_state: Literal["OPEN", "PAUSED", "UNKNOWN", "NOT_SOLD", "NOT_APPLICABLE"]
    cap_state: Literal["LIMITED", "UNLIMITED", "UNKNOWN"]
    daily_limit_amount: Decimal | None
    currency: str
    effective_from: date | None
    source_url: str


class PortfolioCashFlowRead(ApiModel):
    flow_type: Literal["DIVIDEND"]
    occurred_on: date | None
    occurred_year: int
    amount: Decimal
    currency: str
    note: str | None


class PortfolioRecurringPlanRead(ApiModel):
    frequency: Literal["DAILY"]
    gross_amount: Decimal
    fee_pct: Decimal
    net_amount: Decimal
    currency: str


class PortfolioFeeRead(ApiModel):
    platform_purchase_fee_pct: Decimal | None
    standard_purchase_fee_pct: Decimal | None
    reference_discounted_purchase_fee_pct: Decimal | None
    management_fee_pct_annual: Decimal | None
    custody_fee_pct_annual: Decimal | None
    sales_service_fee_pct_annual: Decimal | None
    source_provider: str | None
    source_url: str | None
    snapshot_date: date | None
    has_manual_override: bool


class PortfolioPositionRead(ApiModel):
    id: int
    fund_id: int
    canonical_name: str
    manager_name: str
    share_code: str
    platform: str
    currency: str
    snapshot_date: date
    reported_market_value: Decimal
    reported_profit_amount: Decimal
    reported_return_pct: Decimal
    reported_cumulative_profit_amount: Decimal | None
    anchor_nav_date: date
    anchor_unit_nav: Decimal
    estimated_units: Decimal
    latest_nav_date: date
    latest_unit_nav: Decimal
    latest_daily_return_pct: Decimal | None
    estimated_market_value: Decimal
    estimated_market_value_cny: Decimal | None
    estimated_profit_amount: Decimal
    estimated_profit_amount_cny: Decimal | None
    estimated_return_pct: Decimal
    estimated_cumulative_profit_amount: Decimal | None
    estimated_daily_profit_amount: Decimal | None
    estimated_daily_profit_amount_cny: Decimal | None
    change_since_snapshot: Decimal
    cash_dividend_total: Decimal
    cash_flows: list[PortfolioCashFlowRead]
    recurring_plan: PortfolioRecurringPlanRead | None
    fees: PortfolioFeeRead
    data_quality_note: str | None


class PortfolioCurrencySummaryRead(ApiModel):
    currency: str
    position_count: int
    estimated_market_value: Decimal
    estimated_profit_amount: Decimal
    estimated_return_pct: Decimal | None
    estimated_daily_profit_amount: Decimal | None
    estimated_daily_return_pct: Decimal | None
    recurring_gross_amount: Decimal
    recurring_net_amount: Decimal
    recurring_net_pct: Decimal | None


class PortfolioConvertedSummaryRead(ApiModel):
    currency: Literal["CNY"]
    estimated_market_value: Decimal
    estimated_profit_amount: Decimal
    estimated_return_pct: Decimal | None
    estimated_daily_profit_amount: Decimal | None
    estimated_daily_return_pct: Decimal | None
    usd_cny_rate: Decimal | None
    rate_date: date | None
    source_provider: str | None
    source_url: str | None


class PortfolioRead(ApiModel):
    latest_nav_date: date | None
    positions: list[PortfolioPositionRead]
    currency_summaries: list[PortfolioCurrencySummaryRead]
    converted_summary: PortfolioConvertedSummaryRead | None


class FundSummaryRead(ApiModel):
    id: int
    canonical_name: str
    manager_name: str
    representative_code: str
    strategy_type: str | None
    original_category: str | None
    wrapper_type: str | None
    tech_scope: str
    is_user_selected: bool
    is_dependency: bool
    latest_report_id: int | None = None
    latest_report_status: str | None = None
    latest_report_period_end: date | None = None
    latest_nav_date: date | None = None
    latest_nav_return_pct: Decimal | None = None
    us_country_pct: Decimal | None = None
    korea_country_pct: Decimal | None = None
    japan_country_pct: Decimal | None = None
    hong_kong_country_pct: Decimal | None = None
    china_country_pct: Decimal | None = None
    direct_purchase_limit: PurchaseLimitSummaryRead | None = None
    distribution_purchase_limit: PurchaseLimitSummaryRead | None = None
    metrics: DerivedMetricsRead | None = None


class FundListRead(ApiModel):
    items: list[FundSummaryRead]
    total: int
    offset: int
    limit: int


class ExposureFamilyRead(ApiModel):
    code: str
    display_name: str
    description: str | None
    report_id: int | None
    confidence: Decimal | None
    source_text: str | None


class FundDetailRead(FundSummaryRead):
    exposure_families: list[ExposureFamilyRead] = Field(default_factory=list)


class FundShareRead(ApiModel):
    id: int
    fund_contract_id: int
    share_code: str
    share_class: str | None
    currency: str
    is_exchange_traded: bool
    exchange: str | None


class FundReportRead(ApiModel):
    id: int
    fund_contract_id: int
    report_type: str
    report_year: int
    report_quarter: int | None
    period_start: date | None
    period_end: date
    public_available_at: datetime | None
    source_provider: str
    source_page_url: str | None
    document_url: str | None
    local_document_path: str | None
    mime_type: str | None
    sha256: str | None
    parser_version: str | None
    parse_status: str
    parse_confidence: Decimal | None
    parse_error: str | None


class AllocationItemRead(ApiModel):
    id: int
    name_raw: str
    name_normalized: str
    fair_value_cny: Decimal | None
    nav_pct: Decimal | None
    rank: int | None
    source_section: str
    raw_row: dict[str, Any]
    parse_confidence: Decimal | None


class ExposureRead(ApiModel):
    fund_id: int
    report_id: int | None
    period_end: date | None
    basis: str
    items: list[AllocationItemRead]


class SecurityHoldingRead(ApiModel):
    id: int
    security_code_raw: str | None
    security_name_raw: str
    security_name_normalized: str
    security_name_zh: str | None
    security_name_en: str | None
    exchange_raw: str | None
    market_normalized: str | None
    country_normalized: str | None
    currency: str | None
    quantity: Decimal | None
    fair_value_cny: Decimal | None
    nav_pct: Decimal | None
    rank: int | None
    security_type: str
    exposure_basis: str
    source_section: str
    raw_row: dict[str, Any]
    parse_confidence: Decimal | None


class HoldingsRead(ApiModel):
    fund_id: int
    report_id: int | None
    period_end: date | None
    basis: str
    items: list[SecurityHoldingRead]


class FundHoldingRead(ApiModel):
    id: int
    fund_code_raw: str | None
    fund_name_raw: str
    fund_name_normalized: str
    resolved_fund_contract_id: int | None
    resolved_fund_name: str | None
    currency: str | None
    fair_value_cny: Decimal | None
    nav_pct: Decimal | None
    rank: int | None
    is_unresolved: bool
    exposure_basis: str
    source_section: str
    raw_row: dict[str, Any]
    parse_confidence: Decimal | None


class FundHoldingsRead(ApiModel):
    fund_id: int
    report_id: int | None
    period_end: date | None
    basis: str
    items: list[FundHoldingRead]


class NavPointRead(ApiModel):
    fund_share_id: int
    share_code: str
    nav_date: date
    unit_nav: Decimal
    accumulated_nav: Decimal | None
    published_daily_return_pct: Decimal | None
    calculated_daily_return_pct: Decimal | None
    source_provider: str
    source_published_at: datetime | None
    fetched_at: datetime


class ExchangePriceRead(ApiModel):
    fund_share_id: int
    share_code: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    pct_change: Decimal | None
    volume: Decimal | None
    turnover: Decimal | None
    premium_discount_pct: Decimal | None
    corresponding_nav_date: date | None
    source_provider: str
    fetched_at: datetime


class PurchaseLimitRead(ApiModel):
    id: int
    fund_share_id: int
    share_code: str
    snapshot_date: date
    channel_type: Literal["DIRECT", "DISTRIBUTION"]
    channel_key: str
    channel_name: str
    business_type: Literal["PURCHASE", "RECURRING_INVESTMENT", "CONVERSION_IN"]
    availability_state: Literal["OPEN", "PAUSED", "UNKNOWN", "NOT_SOLD", "NOT_APPLICABLE"]
    cap_state: Literal["LIMITED", "UNLIMITED", "UNKNOWN"]
    daily_limit_amount: Decimal | None
    currency: str
    limit_basis: Literal["PER_ACCOUNT_PER_DAY", "UNKNOWN"]
    share_scope: Literal["PER_SHARE", "ALL_SHARES_COMBINED", "UNKNOWN"]
    effective_from: date | None
    effective_to: date | None
    source_provider: str
    source_url: str
    source_published_at: datetime | None
    fetched_at: datetime
    source_artifact_id: int
    raw_payload_hash: str
    raw_text: str
    confidence: Decimal | None


class PurchaseLimitsRead(ApiModel):
    fund_id: int
    items: list[PurchaseLimitRead]


class PurchaseLimitCoverageRead(ApiModel):
    total_funds: int
    covered_funds: int
    total_shares: int
    covered_shares: int
    latest_snapshot_date: date | None
    availability_state_counts: dict[str, int] = Field(default_factory=dict)
    cap_state_counts: dict[str, int] = Field(default_factory=dict)


class NavHistoryRead(ApiModel):
    fund_id: int
    items: list[NavPointRead]
    exchange_prices: list[ExchangePriceRead]


class FundRelationRead(ApiModel):
    id: int
    source_fund_contract_id: int
    target_fund_contract_id: int | None
    target_fund_name: str | None
    external_target_name: str | None
    external_target_code: str | None
    relation_type: str
    effective_from: date | None
    effective_to: date | None
    report_id: int | None
    weight_nav_pct: Decimal | None
    source_text: str | None
    confidence: Decimal | None


class CompareFundExposureRead(ApiModel):
    fund_id: int
    country: list[AllocationItemRead]
    industry: list[AllocationItemRead]


class OverlapSecurityRead(ApiModel):
    security_code: str | None
    security_name: str
    left_nav_pct: Decimal | None
    right_nav_pct: Decimal | None


class HoldingOverlapRead(ApiModel):
    left_fund_id: int
    right_fund_id: int
    items: list[OverlapSecurityRead]


class CompareNavSeriesRead(ApiModel):
    fund_id: int
    share_code: str | None
    items: list[NavPointRead]


class ReturnCorrelationRead(ApiModel):
    left_fund_id: int
    right_fund_id: int
    common_observations: int
    correlation: Decimal | None


class CompareRead(ApiModel):
    funds: list[FundSummaryRead]
    exposure_basis: str
    exposures: list[CompareFundExposureRead]
    holding_overlaps: list[HoldingOverlapRead]
    nav_series: list[CompareNavSeriesRead]
    return_correlations: list[ReturnCorrelationRead]


class IngestionRunRead(ApiModel):
    id: int
    job_type: str
    status: str
    parameters: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None
    records_seen: int
    records_written: int
    records_failed: int
    error_message: str | None


class DataQualityIssueRead(ApiModel):
    id: int
    ingestion_run_id: int | None
    fund_contract_id: int | None
    fund_report_id: int | None
    fund_share_id: int | None
    issue_code: str
    severity: str
    status: str
    message: str
    details: dict[str, Any]
    detected_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
