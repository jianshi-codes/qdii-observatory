"""Local API for explicit fund selection, research data, and operations status."""

from __future__ import annotations

import base64
import binascii
from collections import Counter, defaultdict
from collections.abc import Generator
from dataclasses import asdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations
from math import sqrt
from typing import Annotated, Literal, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend.app.config import get_settings
from backend.app.coverage import lookthrough_status, report_row_counts
from backend.app.data_operations import (
    NoSelectedFundsError,
    UnknownFundCodesError,
    latest_completed_quarter,
    preparation_status,
    selected_fund_codes,
)
from backend.app.database import get_db
from backend.app.ingestion.catalog_pipeline import import_public_funds
from backend.app.ingestion.http import ProviderHttpClient, ProviderHttpError, RetryPolicy
from backend.app.ingestion.nav_pipeline import sync_nav
from backend.app.ingestion.provider_registry import (
    load_provider_registry,
    provider_client,
    provider_status,
)
from backend.app.ingestion.providers.base import FundCatalogProvider, ProviderSchemaError
from backend.app.ingestion.providers.catalog import (
    RESEARCH_SCOPES,
    SOURCE_CATEGORIES,
    EastmoneyFundCatalogProvider,
)
from backend.app.ingestion.providers.nav import EastmoneyNavProvider
from backend.app.ingestion.storage import StoragePreflightError, raw_data_dir
from backend.app.models import (
    DailyExchangePrice,
    DailyExchangeRate,
    DailyFundFee,
    DailyFundNav,
    DailyPurchaseLimit,
    DataOperation,
    DataQualityIssue,
    FundContract,
    FundExposureFamily,
    FundRelation,
    FundReport,
    FundShare,
    IngestionRun,
    PortfolioPosition,
    ReportCountryAllocation,
    ReportDerivedMetrics,
    ReportFundHolding,
    ReportIndustryAllocation,
    ReportSecurityHolding,
    SourceArtifact,
)
from backend.app.operation_queue import (
    OperationInProgressError,
    enqueue_operation,
    latest_operation,
)
from backend.app.portfolio import import_portfolio_payload
from backend.app.portfolio_import import (
    anchor_missing_codes,
    build_portfolio_preview,
    nav_sync_range,
    parse_portfolio_workbook,
)
from backend.app.q2_analysis import ANALYSIS_START_DATE, MODEL_NAME
from backend.app.q2_analysis.consistency import ConsistencyRules, evaluate_consistency
from backend.app.q2_analysis.market_provider import YahooChartMarketProvider
from backend.app.q2_analysis.portfolio_review import analyze_fund
from backend.app.q2_analysis.predictor import load_consistency_rule_values
from backend.app.q2_analysis.scope import (
    AnalysisScopeError,
    AnalysisTarget,
    select_explicit_active_fund,
    validate_analysis_dates,
)
from backend.app.schemas import (
    AllocationItemRead,
    CompareFundExposureRead,
    CompareNavSeriesRead,
    CompareRead,
    DataOperationRead,
    DataOperationRequest,
    DataPreparationStatusRead,
    DataQualityIssueRead,
    DerivedMetricsRead,
    ExchangePriceRead,
    ExposureFamilyRead,
    ExposureRead,
    FundCatalogCandidatesRead,
    FundCatalogOptionsRead,
    FundCompanyChoiceRead,
    FundDetailRead,
    FundHoldingRead,
    FundHoldingsRead,
    FundListRead,
    FundRelationRead,
    FundReportRead,
    FundShareRead,
    FundSummaryRead,
    FundUniverseStateRead,
    HoldingOverlapRead,
    HoldingsRead,
    IngestionRunRead,
    NavHistoryRead,
    NavPointRead,
    OverlapSecurityRead,
    PortfolioCapabilityRead,
    PortfolioCashFlowRead,
    PortfolioConvertedSummaryRead,
    PortfolioCurrencySummaryRead,
    PortfolioFeeRead,
    PortfolioImportConfirmRequest,
    PortfolioImportFileRequest,
    PortfolioImportPreviewRead,
    PortfolioImportResultRead,
    PortfolioPositionRead,
    PortfolioRead,
    PortfolioRecurringPlanRead,
    PublicFundCandidateRead,
    PublicFundImportRead,
    PublicFundImportRequest,
    PurchaseLimitCoverageRead,
    PurchaseLimitRead,
    PurchaseLimitsRead,
    PurchaseLimitSummaryRead,
    Q2FundAnalysisRead,
    ResearchScopeChoiceRead,
    ReturnCorrelationRead,
    SecurityHoldingRead,
    SourceCategoryChoiceRead,
)

router = APIRouter(prefix="/api")
portfolio_router = APIRouter(prefix="/api")
DbSession = Annotated[Session, Depends(get_db)]
ExposureBasis = Literal["DIRECT", "LOOKTHROUGH"]
PurchaseLimitChannel = Literal["DIRECT", "DISTRIBUTION"]
CENT = Decimal("0.01")
QUANTITY_SCALE = Decimal("0.00000001")
PERCENT_SCALE = Decimal("0.00000001")
PROVIDER_RUN_IDENTITIES = {
    "eastmoney_catalog": ("import_public_funds", "EASTMONEY_FUND_CATALOG"),
    "csrc_reports": ("sync_reports", "CSRC_EID"),
    "eastmoney_nav": ("sync_nav", "EASTMONEY_NAV"),
    "eastmoney_market": ("sync_exchange_prices", "EASTMONEY_MARKET"),
    "ecb_fx": ("sync_exchange_rates", "ECB_REFERENCE_RATE"),
}


def get_fund_catalog_provider() -> Generator[FundCatalogProvider, None, None]:
    registry = load_provider_registry()
    config = registry.get("eastmoney_catalog")
    if config is None or not config.enabled:
        raise HTTPException(status_code=503, detail="Public fund catalog provider is disabled")
    with ProviderHttpClient(
        timeout_seconds=config.timeout_seconds,
        min_interval_seconds=1 / config.rate_limit_per_second,
        retry=RetryPolicy(attempts=config.retry_attempts),
        user_agent=config.user_agent,
    ) as http:
        yield EastmoneyFundCatalogProvider(http)


CatalogProvider = Annotated[FundCatalogProvider, Depends(get_fund_catalog_provider)]


def _normalize_basis(value: str) -> ExposureBasis:
    normalized = value.strip().upper().replace("-", "").replace("_", "")
    if normalized not in {"DIRECT", "LOOKTHROUGH"}:
        raise HTTPException(
            status_code=422,
            detail="basis must be DIRECT or LOOKTHROUGH",
        )
    return cast(ExposureBasis, normalized)


def _get_fund(db: Session, fund_id: int) -> FundContract:
    fund = db.get(FundContract, fund_id)
    if fund is None:
        raise HTTPException(status_code=404, detail="Fund contract not found")
    return fund


def _latest_reports(db: Session, fund_ids: list[int]) -> dict[int, FundReport]:
    if not fund_ids:
        return {}
    reports = db.scalars(
        select(FundReport)
        .where(FundReport.fund_contract_id.in_(fund_ids))
        .order_by(
            FundReport.fund_contract_id,
            FundReport.period_end.desc(),
            FundReport.id.desc(),
        )
    ).all()
    latest: dict[int, FundReport] = {}
    for report in reports:
        latest.setdefault(report.fund_contract_id, report)
    return latest


def _latest_representative_nav(db: Session, fund_ids: list[int]) -> dict[int, DailyFundNav]:
    if not fund_ids:
        return {}
    rows = db.execute(
        select(FundShare.fund_contract_id, DailyFundNav)
        .join(DailyFundNav, DailyFundNav.fund_share_id == FundShare.id)
        .join(FundContract, FundContract.id == FundShare.fund_contract_id)
        .where(
            FundShare.fund_contract_id.in_(fund_ids),
            FundShare.share_code == FundContract.representative_code,
        )
        .order_by(
            FundShare.fund_contract_id,
            DailyFundNav.nav_date.desc(),
            DailyFundNav.id.desc(),
        )
    ).all()
    latest: dict[int, DailyFundNav] = {}
    for fund_id, nav in rows:
        latest.setdefault(fund_id, nav)
    return latest


def _country_percentages(db: Session, report_ids: list[int]) -> dict[int, dict[str, Decimal]]:
    if not report_ids:
        return {}
    aliases = {
        "US": "US",
        "美国": "US",
        "UNITED STATES": "US",
        "KR": "KR",
        "韩国": "KR",
        "SOUTH KOREA": "KR",
        "JP": "JP",
        "日本": "JP",
        "JAPAN": "JP",
        "HK": "HK",
        "香港": "HK",
        "中国香港": "HK",
        "HONG KONG": "HK",
        "HONGKONG": "HK",
        "CN": "CN",
        "中国": "CN",
        "中国大陆": "CN",
        "CHINA": "CN",
    }
    result: dict[int, dict[str, Decimal]] = defaultdict(dict)
    rows = db.execute(
        select(
            ReportCountryAllocation.fund_report_id,
            ReportCountryAllocation.country_name_normalized,
            ReportCountryAllocation.nav_pct,
        ).where(
            ReportCountryAllocation.fund_report_id.in_(report_ids),
            ReportCountryAllocation.exposure_basis == "DIRECT",
            ReportCountryAllocation.nav_pct.is_not(None),
        )
    ).all()
    for report_id, country_name, nav_pct in rows:
        country = aliases.get(country_name.strip().upper())
        if country is None or nav_pct is None:
            continue
        result[report_id][country] = result[report_id].get(country, Decimal("0")) + nav_pct
    return result


def _representative_purchase_limits(
    db: Session, funds: list[FundContract]
) -> dict[int, dict[str, DailyPurchaseLimit]]:
    if not funds:
        return {}
    representative_codes = {fund.representative_code: fund.id for fund in funds}
    shares = db.execute(
        select(FundShare.id, FundShare.share_code).where(
            FundShare.share_code.in_(representative_codes)
        )
    ).all()
    share_to_fund = {share_id: representative_codes[share_code] for share_id, share_code in shares}
    if not share_to_fund:
        return {}
    rows = list(
        db.scalars(
            select(DailyPurchaseLimit)
            .where(
                DailyPurchaseLimit.fund_share_id.in_(share_to_fund),
                DailyPurchaseLimit.business_type == "PURCHASE",
            )
            .order_by(
                DailyPurchaseLimit.fund_share_id,
                DailyPurchaseLimit.snapshot_date.desc(),
                DailyPurchaseLimit.id.desc(),
            )
        ).all()
    )
    latest_dates: dict[int, date] = {}
    for row in rows:
        latest_dates.setdefault(row.fund_share_id, row.snapshot_date)
    candidates: dict[int, dict[str, list[DailyPurchaseLimit]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        if row.snapshot_date == latest_dates[row.fund_share_id]:
            candidates[share_to_fund[row.fund_share_id]][row.channel_type].append(row)

    def priority(row: DailyPurchaseLimit) -> tuple[int, int, int, int]:
        channel_priority = {
            "ALL_DISTRIBUTORS": 0,
            "EASTMONEY_TIANTIAN": 1,
        }.get(row.channel_key, 2)
        cap_priority = 0 if row.cap_state != "UNKNOWN" else 1
        availability_priority = 0 if row.availability_state != "UNKNOWN" else 1
        return channel_priority, cap_priority, availability_priority, -row.id

    return {
        fund_id: {
            channel_type: min(channel_rows, key=priority)
            for channel_type, channel_rows in by_channel.items()
        }
        for fund_id, by_channel in candidates.items()
    }


def _limit_summary(row: DailyPurchaseLimit | None) -> PurchaseLimitSummaryRead | None:
    if row is None:
        return None
    return PurchaseLimitSummaryRead(
        snapshot_date=row.snapshot_date,
        channel_type=cast(PurchaseLimitChannel, row.channel_type),
        channel_key=row.channel_key,
        channel_name=row.channel_name,
        availability_state=cast(
            Literal["OPEN", "PAUSED", "UNKNOWN", "NOT_SOLD", "NOT_APPLICABLE"],
            row.availability_state,
        ),
        cap_state=cast(Literal["LIMITED", "UNLIMITED", "UNKNOWN"], row.cap_state),
        daily_limit_amount=row.daily_limit_amount,
        currency=row.currency,
        effective_from=row.effective_from,
        source_url=row.source_url,
    )


def _fund_summaries(db: Session, funds: list[FundContract]) -> list[FundSummaryRead]:
    fund_ids = [fund.id for fund in funds]
    reports = _latest_reports(db, fund_ids)
    nav_rows = _latest_representative_nav(db, fund_ids)
    report_ids = [report.id for report in reports.values()]
    countries_by_report = _country_percentages(db, report_ids)
    limits_by_fund = _representative_purchase_limits(db, funds)
    stock_counts = report_row_counts(
        db, ReportSecurityHolding, report_ids, basis="DIRECT"
    )
    fund_counts = report_row_counts(db, ReportFundHolding, report_ids, basis="DIRECT")
    lookthrough_country_counts = report_row_counts(
        db, ReportCountryAllocation, report_ids, basis="LOOKTHROUGH"
    )
    lookthrough_industry_counts = report_row_counts(
        db, ReportIndustryAllocation, report_ids, basis="LOOKTHROUGH"
    )
    metrics_by_report: dict[int, ReportDerivedMetrics] = {}
    if report_ids:
        metrics_by_report = {
            item.fund_report_id: item
            for item in db.scalars(
                select(ReportDerivedMetrics).where(
                    ReportDerivedMetrics.fund_report_id.in_(report_ids)
                )
            ).all()
        }

    result: list[FundSummaryRead] = []
    for fund in funds:
        report = reports.get(fund.id)
        report_id = report.id if report else 0
        metrics = metrics_by_report.get(report.id) if report else None
        nav = nav_rows.get(fund.id)
        countries = countries_by_report.get(report.id, {}) if report else {}
        limits = limits_by_fund.get(fund.id, {})
        us_country_pct = countries.get("US")
        if us_country_pct is None and metrics:
            us_country_pct = metrics.us_country_pct
        korea_country_pct = countries.get("KR")
        if korea_country_pct is None and metrics:
            korea_country_pct = metrics.korea_country_pct
        hong_kong_country_pct = countries.get("HK")
        if hong_kong_country_pct is None and metrics:
            hong_kong_country_pct = metrics.hong_kong_country_pct
        result.append(
            FundSummaryRead(
                id=fund.id,
                canonical_name=fund.canonical_name,
                manager_name=fund.manager_name,
                representative_code=fund.representative_code,
                strategy_type=fund.strategy_type,
                original_category=fund.original_category,
                wrapper_type=fund.wrapper_type,
                tech_scope=metrics.tech_scope if metrics else fund.tech_scope,
                is_user_selected=fund.is_user_selected,
                is_dependency=fund.is_dependency,
                latest_report_id=report.id if report else None,
                latest_report_status=report.parse_status if report else None,
                latest_report_period_end=report.period_end if report else None,
                parse_confidence=report.parse_confidence if report else None,
                stock_holding_count=stock_counts.get(report_id, 0),
                fund_holding_count=fund_counts.get(report_id, 0),
                lookthrough_status=lookthrough_status(
                    status=(report.parse_status or "").strip().lower()
                    if report
                    else "unresolved",
                    fund_holding_count=fund_counts.get(report_id, 0),
                    lookthrough_row_count=(
                        lookthrough_country_counts.get(report_id, 0)
                        + lookthrough_industry_counts.get(report_id, 0)
                    ),
                    metrics=metrics,
                ),
                latest_nav_date=nav.nav_date if nav else None,
                latest_nav_return_pct=(
                    nav.published_daily_return_pct
                    if nav and nav.published_daily_return_pct is not None
                    else nav.calculated_daily_return_pct
                    if nav
                    else None
                ),
                us_country_pct=us_country_pct,
                korea_country_pct=korea_country_pct,
                japan_country_pct=countries.get("JP"),
                hong_kong_country_pct=hong_kong_country_pct,
                china_country_pct=countries.get("CN"),
                direct_purchase_limit=_limit_summary(limits.get("DIRECT")),
                distribution_purchase_limit=_limit_summary(limits.get("DISTRIBUTION")),
                metrics=DerivedMetricsRead.model_validate(metrics) if metrics else None,
            )
        )
    return result


def _resolve_report(db: Session, fund_id: int, report_id: int | None) -> FundReport | None:
    _get_fund(db, fund_id)
    if report_id is not None:
        report = db.scalar(
            select(FundReport).where(
                FundReport.id == report_id,
                FundReport.fund_contract_id == fund_id,
            )
        )
        if report is None:
            raise HTTPException(status_code=404, detail="Report not found for this fund")
        return report
    return db.scalar(
        select(FundReport)
        .where(FundReport.fund_contract_id == fund_id)
        .order_by(FundReport.period_end.desc(), FundReport.id.desc())
        .limit(1)
    )


def _allocation_item(
    row: ReportCountryAllocation | ReportIndustryAllocation,
    name_raw: str,
    name_normalized: str,
) -> AllocationItemRead:
    return AllocationItemRead(
        id=row.id,
        name_raw=name_raw,
        name_normalized=name_normalized,
        fair_value_cny=row.fair_value_cny,
        nav_pct=row.nav_pct,
        rank=row.rank,
        source_section=row.source_section,
        raw_row=row.raw_row,
        parse_confidence=row.parse_confidence,
    )


def _allocation_items(
    db: Session,
    model: type[ReportCountryAllocation] | type[ReportIndustryAllocation],
    report_id: int,
    basis: ExposureBasis,
) -> list[AllocationItemRead]:
    if model is ReportCountryAllocation:
        country_rows = db.scalars(
            select(ReportCountryAllocation)
            .where(
                ReportCountryAllocation.fund_report_id == report_id,
                ReportCountryAllocation.exposure_basis == basis,
            )
            .order_by(
                ReportCountryAllocation.rank.asc().nulls_last(),
                ReportCountryAllocation.nav_pct.desc().nulls_last(),
            )
        ).all()
        return [
            _allocation_item(
                row,
                row.country_name_raw,
                row.country_name_normalized,
            )
            for row in country_rows
        ]
    industry_rows = db.scalars(
        select(ReportIndustryAllocation)
        .where(
            ReportIndustryAllocation.fund_report_id == report_id,
            ReportIndustryAllocation.exposure_basis == basis,
        )
        .order_by(
            ReportIndustryAllocation.rank.asc().nulls_last(),
            ReportIndustryAllocation.nav_pct.desc().nulls_last(),
        )
    ).all()
    return [
        _allocation_item(
            row,
            row.industry_name_raw,
            row.industry_name_normalized,
        )
        for row in industry_rows
    ]


def _nav_point(row: DailyFundNav, share_code: str) -> NavPointRead:
    return NavPointRead(
        fund_share_id=row.fund_share_id,
        share_code=share_code,
        nav_date=row.nav_date,
        unit_nav=row.unit_nav,
        accumulated_nav=row.accumulated_nav,
        published_daily_return_pct=row.published_daily_return_pct,
        calculated_daily_return_pct=row.calculated_daily_return_pct,
        source_provider=row.source_provider,
        source_published_at=row.source_published_at,
        fetched_at=row.fetched_at,
    )


@router.get("/funds", response_model=FundListRead)
def list_funds(
    db: DbSession,
    manager_name: str | None = None,
    original_category: str | None = None,
    tech_scope: str | None = None,
    wrapper_type: str | None = None,
    is_user_selected: bool | None = True,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> FundListRead:
    filters = []
    if manager_name:
        filters.append(FundContract.manager_name == manager_name)
    if original_category:
        filters.append(FundContract.original_category == original_category)
    if tech_scope:
        filters.append(FundContract.tech_scope == tech_scope)
    if wrapper_type:
        filters.append(FundContract.wrapper_type == wrapper_type)
    if is_user_selected is not None:
        filters.append(FundContract.is_user_selected == is_user_selected)

    total = db.scalar(select(func.count(FundContract.id)).where(*filters)) or 0
    funds = db.scalars(
        select(FundContract)
        .where(*filters)
        .order_by(FundContract.representative_code)
        .offset(offset)
        .limit(limit)
    ).all()
    return FundListRead(
        items=_fund_summaries(db, list(funds)), total=total, offset=offset, limit=limit
    )


@router.post("/funds/{fund_id}/archive", response_model=FundUniverseStateRead)
def archive_fund(fund_id: int, db: DbSession) -> FundUniverseStateRead:
    active_operation = db.scalar(
        select(DataOperation).where(DataOperation.active_slot == 1).limit(1)
    )
    if active_operation is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"data operation {active_operation.id} ({active_operation.operation}) "
                f"is {active_operation.status}; archive after it finishes"
            ),
        )

    fund = _get_fund(db, fund_id)
    fund.is_user_selected = False
    db.commit()
    return FundUniverseStateRead.model_validate(fund)


def _not_applicable_estimate(
    db: Session,
    fund: FundContract,
    share: FundShare,
    *,
    start_date: date,
    as_of: date,
) -> Q2FundAnalysisRead:
    report = db.scalar(
        select(FundReport)
        .where(
            FundReport.fund_contract_id == fund.id,
            FundReport.report_type == "QUARTERLY",
            FundReport.report_year == 2026,
            FundReport.report_quarter == 2,
        )
        .order_by(FundReport.period_end.desc(), FundReport.id.desc())
        .limit(1)
    )
    latest_nav_date = db.scalar(
        select(func.max(DailyFundNav.nav_date)).where(
            DailyFundNav.fund_share_id == share.id,
            DailyFundNav.nav_date >= start_date,
            DailyFundNav.nav_date <= as_of,
        )
    )
    consistency = evaluate_consistency(
        [],
        ConsistencyRules.from_mapping(load_consistency_rule_values()),
        not_applicable=True,
    )
    return Q2FundAnalysisRead.model_validate(
        {
            "fund_id": fund.id,
            "fund_code": share.share_code,
            "representative_code": fund.representative_code,
            "fund_name": fund.canonical_name,
            "share_code": share.share_code,
            "share_currency": share.currency,
            "data_as_of": latest_nav_date or (report.period_end if report else as_of),
            "market_data_fetched_at": None,
            "report_period_end": report.period_end if report else None,
            "report_public_available_at": report.public_available_at if report else None,
            "analysis_start_date": start_date,
            "as_of": as_of,
            "analysis_mode": None,
            "model": MODEL_NAME,
            "prediction": None,
            "latest_comparison": None,
            "consistency": consistency.as_dict(),
            "coverage": None,
            "prediction_observation_coverage_pct": None,
            "proxies": [],
            "unmapped_securities": [],
            "limitations": [consistency.explanation],
            "sources": [],
            "market_data_errors": [],
            "series": [],
        }
    )


@router.get("/funds/{fund_id}/today-estimate", response_model=Q2FundAnalysisRead)
def get_fund_today_estimate(
    fund_id: int,
    db: DbSession,
    share_code: str | None = None,
    start_date: date = ANALYSIS_START_DATE,
    as_of: date | None = None,
    refresh_market_data: bool = False,
) -> Q2FundAnalysisRead:
    resolved_as_of = as_of or date.today()
    try:
        validate_analysis_dates(start_date, resolved_as_of)
    except AnalysisScopeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    fund = _get_fund(db, fund_id)
    selected_code = share_code or fund.representative_code
    share = db.scalar(
        select(FundShare).where(
            FundShare.fund_contract_id == fund.id,
            FundShare.share_code == selected_code,
        )
    )
    if share is None:
        raise HTTPException(status_code=404, detail="Share code not found for this fund")
    if (fund.wrapper_type or "").upper() != "DIRECT":
        return _not_applicable_estimate(
            db,
            fund,
            share,
            start_date=start_date,
            as_of=resolved_as_of,
        )

    try:
        target: AnalysisTarget = select_explicit_active_fund(db, share.share_code)
    except AnalysisScopeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    with ProviderHttpClient() as http:
        result = analyze_fund(
            db,
            target,
            YahooChartMarketProvider(http),
            start_date=start_date,
            as_of=resolved_as_of,
            refresh_market_data=refresh_market_data,
        )
    return Q2FundAnalysisRead.model_validate(result.as_dict(include_series=False))


@router.get("/fund-catalog/options", response_model=FundCatalogOptionsRead)
def get_fund_catalog_options(provider: CatalogProvider) -> FundCatalogOptionsRead:
    try:
        companies = provider.companies()
    except (ProviderSchemaError, ProviderHttpError, ValueError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return FundCatalogOptionsRead(
        companies=[
            FundCompanyChoiceRead(
                company_code=item.company_code,
                company_name=item.company_name,
            )
            for item in companies
        ],
        source_categories=[
            SourceCategoryChoiceRead(value=value, label=label) for value, label in SOURCE_CATEGORIES
        ],
        research_scopes=[
            ResearchScopeChoiceRead(value=value, label=label) for value, label in RESEARCH_SCOPES
        ],
        source_provider=provider.name,
        source_notice="第三方公开目录可能延迟或变更；导入前请核对基金公司正式信息。",
    )


@router.get("/fund-catalog/candidates", response_model=FundCatalogCandidatesRead)
def get_fund_catalog_candidates(
    provider: CatalogProvider,
    company_code: Annotated[str | None, Query(pattern=r"^[0-9]{8}$")] = None,
    source_category: Annotated[
        str | None,
        Query(pattern=r"^(311|312|313|317|320|330|340)$"),
    ] = None,
    category: str | None = None,
    research_scope: str | None = None,
) -> FundCatalogCandidatesRead:
    try:
        snapshot = (
            provider.discover_company(company_code)
            if company_code
            else provider.discover_public(source_category)
        )
        source_codes = (
            {item.fund_code for item in provider.discover_public(source_category).candidates}
            if company_code and source_category
            else None
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (ProviderSchemaError, ProviderHttpError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    categories = sorted({item.category for item in snapshot.candidates})
    candidates = [
        item
        for item in snapshot.candidates
        if (source_codes is None or item.fund_code in source_codes)
        and (category is None or item.category == category)
        and (research_scope in (None, "ALL") or item.research_scope == research_scope)
    ]
    return FundCatalogCandidatesRead(
        items=[PublicFundCandidateRead.model_validate(item) for item in candidates],
        categories=categories,
        total=len(candidates),
        source_provider=provider.name,
    )


@router.get("/fund-catalog/lookup/{fund_code}", response_model=PublicFundCandidateRead)
def lookup_public_fund(
    provider: CatalogProvider,
    fund_code: Annotated[str, Path(pattern=r"^[0-9]{6}$")],
) -> PublicFundCandidateRead:
    try:
        snapshot = provider.lookup(fund_code)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (ProviderSchemaError, ProviderHttpError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return PublicFundCandidateRead.model_validate(snapshot.candidates[0])


@router.post("/fund-catalog/import", response_model=PublicFundImportRead)
def import_selected_public_funds(
    request: PublicFundImportRequest,
    db: DbSession,
    provider: CatalogProvider,
) -> PublicFundImportRead:
    codes = tuple(dict.fromkeys(code.strip() for code in request.fund_codes))
    invalid = [code for code in codes if len(code) != 6 or not code.isdigit()]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Invalid six-digit fund codes: {invalid}")
    try:
        raw_root = raw_data_dir()
    except StoragePreflightError as error:
        raise HTTPException(
            status_code=503,
            detail=f"Raw data storage is unavailable: {error}",
        ) from error
    result = import_public_funds(db, provider, raw_root, codes)
    return PublicFundImportRead(
        status=result.status,
        imported_codes=list(result.imported_codes),
        failures=result.failures,
    )


def _data_operation_response(result: DataOperation) -> DataOperationRead:
    return DataOperationRead.model_validate(result)


def _data_operation_inputs(
    db: Session,
    request: DataOperationRequest,
) -> tuple[str, ...]:
    codes = selected_fund_codes(db, set(request.fund_codes) or None)
    raw_data_dir()
    return codes


def _raise_data_operation_error(error: Exception) -> NoReturn:
    if isinstance(error, OperationInProgressError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, NoSelectedFundsError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, UnknownFundCodesError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, StoragePreflightError):
        raise HTTPException(status_code=503, detail=str(error)) from error
    raise error


def _enqueue_data_operation(
    operation: str,
    request: DataOperationRequest,
    db: Session,
) -> DataOperationRead:
    try:
        codes = _data_operation_inputs(db, request)
        year, quarter = latest_completed_quarter()
        return _data_operation_response(
            enqueue_operation(
                db,
                operation=operation,
                fund_codes=codes,
                lookback_days=request.lookback_days,
                report_year=year,
                report_quarter=quarter,
            )
        )
    except Exception as error:
        _raise_data_operation_error(error)


@router.get("/operations/preparation-status", response_model=DataPreparationStatusRead)
def get_data_preparation_status(db: DbSession) -> DataPreparationStatusRead:
    status = preparation_status(db)
    latest = latest_operation(db)
    active = latest if latest is not None and latest.status in {"queued", "running"} else None
    return DataPreparationStatusRead(
        **asdict(status),
        active_operation=active.operation if active is not None else None,
        latest_operation=(_data_operation_response(latest) if latest is not None else None),
    )


@router.get("/operations/{operation_id}", response_model=DataOperationRead)
def get_data_operation(operation_id: int, db: DbSession) -> DataOperationRead:
    item = db.get(DataOperation, operation_id)
    if item is None:
        raise HTTPException(status_code=404, detail="data operation not found")
    return _data_operation_response(item)


@router.post("/operations/prepare", response_model=DataOperationRead, status_code=202)
def prepare_imported_fund_data(
    request: DataOperationRequest,
    db: DbSession,
) -> DataOperationRead:
    return _enqueue_data_operation("prepare", request, db)


@router.post("/operations/sync-daily", response_model=DataOperationRead, status_code=202)
def sync_imported_fund_daily_data(
    request: DataOperationRequest,
    db: DbSession,
) -> DataOperationRead:
    return _enqueue_data_operation("sync-daily", request, db)


@router.post("/operations/sync-sales-limits", response_model=DataOperationRead, status_code=202)
def sync_imported_fund_sales_limits(
    request: DataOperationRequest,
    db: DbSession,
) -> DataOperationRead:
    return _enqueue_data_operation("sync-sales-limits", request, db)


@router.post("/operations/sync-reports", response_model=DataOperationRead, status_code=202)
def sync_imported_fund_reports(
    request: DataOperationRequest,
    db: DbSession,
) -> DataOperationRead:
    return _enqueue_data_operation("sync-reports", request, db)


@router.post("/operations/parse-reports", response_model=DataOperationRead, status_code=202)
def parse_imported_fund_reports(
    request: DataOperationRequest,
    db: DbSession,
) -> DataOperationRead:
    return _enqueue_data_operation("parse-reports", request, db)


@router.get("/purchase-limit-coverage", response_model=PurchaseLimitCoverageRead)
def get_purchase_limit_coverage(db: DbSession) -> PurchaseLimitCoverageRead:
    """Summarize selected-fund coverage on the globally latest snapshot date."""

    fund_ids = list(
        db.scalars(select(FundContract.id).where(FundContract.is_user_selected.is_(True))).all()
    )
    share_rows = db.execute(
        select(FundShare.id, FundShare.fund_contract_id).where(
            FundShare.fund_contract_id.in_(fund_ids)
        )
    ).all()
    share_to_fund = {share_id: fund_id for share_id, fund_id in share_rows}
    if not share_to_fund:
        return PurchaseLimitCoverageRead(
            total_funds=len(fund_ids),
            covered_funds=0,
            total_shares=0,
            covered_shares=0,
            latest_snapshot_date=None,
        )

    latest_snapshot_date = db.scalar(
        select(func.max(DailyPurchaseLimit.snapshot_date)).where(
            DailyPurchaseLimit.fund_share_id.in_(share_to_fund)
        )
    )
    if latest_snapshot_date is None:
        return PurchaseLimitCoverageRead(
            total_funds=len(fund_ids),
            covered_funds=0,
            total_shares=len(share_to_fund),
            covered_shares=0,
            latest_snapshot_date=None,
        )

    latest_rows = list(
        db.scalars(
            select(DailyPurchaseLimit).where(
                DailyPurchaseLimit.fund_share_id.in_(share_to_fund),
                DailyPurchaseLimit.snapshot_date == latest_snapshot_date,
            )
        ).all()
    )
    covered_share_ids = {row.fund_share_id for row in latest_rows}
    return PurchaseLimitCoverageRead(
        total_funds=len(fund_ids),
        covered_funds=len({share_to_fund[share_id] for share_id in covered_share_ids}),
        total_shares=len(share_to_fund),
        covered_shares=len(covered_share_ids),
        latest_snapshot_date=latest_snapshot_date,
        availability_state_counts=dict(
            sorted(Counter(row.availability_state for row in latest_rows).items())
        ),
        cap_state_counts=dict(sorted(Counter(row.cap_state for row in latest_rows).items())),
    )


def _latest_provider_run(db: Session, provider_name: str) -> IngestionRun | None:
    identity = PROVIDER_RUN_IDENTITIES.get(provider_name)
    if identity is None:
        return None
    job_type, run_provider = identity
    return db.scalar(
        select(IngestionRun)
        .where(
            IngestionRun.job_type == job_type,
            IngestionRun.finished_at.is_not(None),
            IngestionRun.parameters["provider"].as_string() == run_provider,
        )
        .order_by(IngestionRun.finished_at.desc(), IngestionRun.id.desc())
        .limit(1)
    )


@router.get("/provider-health")
def get_provider_health(db: DbSession) -> dict[str, object]:
    registry = load_provider_registry()
    providers: list[dict[str, object]] = []
    for name, config in registry.items():
        observation = _latest_provider_run(db, name) if config.enabled else None
        providers.append(
            {
                "name": name,
                "enabled": config.enabled,
                "priority": config.priority,
                "status": provider_status(
                    config,
                    run_status=observation.status if observation else None,
                    error_message=observation.error_message if observation else None,
                ).value,
                "last_checked_at": observation.finished_at if observation else None,
                "last_run_status": observation.status if observation else None,
                "records_failed": observation.records_failed if observation else None,
            }
        )
    return {"providers": providers}


@router.get("/portfolio/capability", response_model=PortfolioCapabilityRead)
def get_portfolio_capability() -> PortfolioCapabilityRead:
    return PortfolioCapabilityRead(
        enabled=get_settings().portfolio_enabled,
        template_url="/templates/portfolio-import-template.xlsx",
    )


def _decode_portfolio_file(request: PortfolioImportFileRequest) -> bytes:
    if not request.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=422, detail="只支持 .xlsx 持仓模板")
    try:
        return base64.b64decode(request.content_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status_code=422, detail="上传文件不是有效的 Base64 内容") from error


def _portfolio_import_contract_states(
    db: Session,
) -> dict[int, tuple[bool, bool]]:
    return {
        contract.id: (contract.is_user_selected, contract.is_dependency)
        for contract in db.scalars(select(FundContract)).all()
    }


def _restore_portfolio_import_contract_states(
    db: Session,
    share_codes: set[str],
    prior_states: dict[int, tuple[bool, bool]],
) -> None:
    """Undo active-universe changes while retaining imported public catalog evidence."""

    db.rollback()
    contracts: dict[int, FundContract] = {}
    for share in db.scalars(select(FundShare).where(FundShare.share_code.in_(share_codes))):
        contracts[share.fund_contract_id] = share.fund_contract
    for contract in contracts.values():
        previous = prior_states.get(contract.id)
        if previous is None:
            contract.is_user_selected = False
            contract.is_dependency = False
        else:
            contract.is_user_selected, contract.is_dependency = previous
    db.commit()


@portfolio_router.post(
    "/portfolio/import/preview",
    response_model=PortfolioImportPreviewRead,
)
def preview_portfolio_import(
    request: PortfolioImportFileRequest,
    db: DbSession,
    provider: CatalogProvider,
) -> PortfolioImportPreviewRead:
    try:
        workbook = parse_portfolio_workbook(_decode_portfolio_file(request))
        preview = build_portfolio_preview(db, workbook, provider)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (ProviderSchemaError, ProviderHttpError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return PortfolioImportPreviewRead.model_validate(preview)


@portfolio_router.post(
    "/portfolio/import/confirm",
    response_model=PortfolioImportResultRead,
)
def confirm_portfolio_import(
    request: PortfolioImportConfirmRequest,
    db: DbSession,
    provider: CatalogProvider,
) -> PortfolioImportResultRead:
    try:
        workbook = parse_portfolio_workbook(_decode_portfolio_file(request))
        preview = build_portfolio_preview(db, workbook, provider)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (ProviderSchemaError, ProviderHttpError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    if workbook.file_digest != request.file_digest:
        raise HTTPException(status_code=409, detail="文件已变化，请重新预览后再确认")
    if not preview["valid"]:
        raise HTTPException(status_code=422, detail="文件校验未通过，请修正后重新预览")

    try:
        raw_root = raw_data_dir()
    except StoragePreflightError as error:
        raise HTTPException(status_code=503, detail=f"本地数据目录不可用：{error}") from error

    positions = preview["positions"]
    affected_codes = {str(item["share_code"]) for item in positions}
    prior_contract_states = _portfolio_import_contract_states(db)
    add_codes = tuple(
        sorted({item["share_code"] for item in positions if item["universe_action"] == "ADD"})
    )
    restore_codes = sorted(
        {item["share_code"] for item in positions if item["universe_action"] == "RESTORE"}
    )
    imported_codes: list[str] = []
    missing_nav: set[str] = set()
    try:
        if add_codes:
            public_result = import_public_funds(db, provider, raw_root, add_codes)
            if public_result.failures:
                failures = "；".join(
                    f"{code}: {message}" for code, message in public_result.failures.items()
                )
                raise HTTPException(status_code=502, detail=f"加入基金 universe 失败：{failures}")
            imported_codes = list(public_result.imported_codes)

        for raw in workbook.payload["positions"]:
            share = db.scalar(
                select(FundShare).where(FundShare.share_code == str(raw["share_code"]))
            )
            if share is None:
                raise HTTPException(
                    status_code=502,
                    detail=f"基金 {raw['share_code']} 加入 universe 后仍不存在",
                )
            share.fund_contract.is_user_selected = True
            share.fund_contract.is_dependency = False
        db.commit()

        missing_nav = anchor_missing_codes(db, workbook)
        if missing_nav:
            start_date, end_date = nav_sync_range(workbook)
            try:
                with provider_client("eastmoney_nav") as http:
                    sync_nav(
                        db,
                        EastmoneyNavProvider(http),
                        raw_root,
                        start_date=start_date,
                        end_date=end_date,
                        share_codes=missing_nav,
                        page_size=EastmoneyNavProvider.max_page_size,
                    )
            except Exception as error:
                raise HTTPException(
                    status_code=502, detail=f"补充基金净值失败：{error}"
                ) from error
            still_missing = anchor_missing_codes(db, workbook)
            if still_missing:
                raise HTTPException(
                    status_code=422,
                    detail=f"这些基金在快照日期前没有可用净值：{sorted(still_missing)}",
                )

        try:
            result = import_portfolio_payload(db, workbook.payload)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=f"写入持仓失败：{error}") from error
    except Exception:
        _restore_portfolio_import_contract_states(
            db,
            affected_codes,
            prior_contract_states,
        )
        raise
    return PortfolioImportResultRead(
        positions_written=result.positions_written,
        cash_flows_written=result.cash_flows_written,
        universe_added=sorted(imported_codes),
        universe_restored=restore_codes,
        nav_synced=sorted(missing_nav),
    )


@portfolio_router.get("/portfolio", response_model=PortfolioRead)
def get_portfolio(db: DbSession) -> PortfolioRead:
    positions = list(
        db.scalars(
            select(PortfolioPosition)
            .where(PortfolioPosition.is_active.is_(True))
            .order_by(PortfolioPosition.platform, PortfolioPosition.id)
        ).all()
    )
    if not positions:
        return PortfolioRead(
            latest_nav_date=None,
            positions=[],
            currency_summaries=[],
            converted_summary=None,
        )
    share_ids = {position.fund_share_id for position in positions}
    navs_by_share: dict[int, list[DailyFundNav]] = defaultdict(list)
    for nav in db.scalars(
        select(DailyFundNav)
        .where(DailyFundNav.fund_share_id.in_(share_ids))
        .order_by(DailyFundNav.fund_share_id, DailyFundNav.nav_date.desc(), DailyFundNav.id.desc())
    ).all():
        if len(navs_by_share[nav.fund_share_id]) < 2:
            navs_by_share[nav.fund_share_id].append(nav)
    fees_by_share: dict[int, DailyFundFee] = {}
    for fee_row in db.scalars(
        select(DailyFundFee)
        .where(DailyFundFee.fund_share_id.in_(share_ids))
        .order_by(
            DailyFundFee.fund_share_id,
            DailyFundFee.snapshot_date.desc(),
            DailyFundFee.id.desc(),
        )
    ).all():
        fees_by_share.setdefault(fee_row.fund_share_id, fee_row)
    usd_cny_rate = db.scalar(
        select(DailyExchangeRate)
        .where(
            DailyExchangeRate.base_currency == "USD",
            DailyExchangeRate.quote_currency == "CNY",
        )
        .order_by(DailyExchangeRate.rate_date.desc(), DailyExchangeRate.id.desc())
        .limit(1)
    )

    result: list[PortfolioPositionRead] = []
    converted_market = Decimal("0")
    converted_profit = Decimal("0")
    converted_daily_profit = Decimal("0")
    converted_cost_basis = Decimal("0")
    conversion_complete = True
    converted_daily_complete = True
    converted_cost_complete = True
    summaries: dict[str, dict[str, Decimal | int | None]] = defaultdict(
        lambda: {
            "position_count": 0,
            "estimated_market_value": Decimal("0"),
            "estimated_profit_amount": Decimal("0"),
            "estimated_cost_basis": Decimal("0"),
            "cost_basis_count": 0,
            "estimated_daily_profit_amount": Decimal("0"),
            "daily_profit_count": 0,
            "recurring_gross_amount": Decimal("0"),
            "recurring_net_amount": Decimal("0"),
        }
    )
    for position in positions:
        nav_rows = navs_by_share.get(position.fund_share_id, [])
        latest_nav_date = nav_rows[0].nav_date if nav_rows else position.anchor_nav_date
        latest_unit_nav = nav_rows[0].unit_nav if nav_rows else position.anchor_unit_nav
        previous_unit_nav = nav_rows[1].unit_nav if len(nav_rows) > 1 else None
        latest_daily_return = None
        if nav_rows:
            latest_daily_return = (
                nav_rows[0].published_daily_return_pct
                if nav_rows[0].published_daily_return_pct is not None
                else nav_rows[0].calculated_daily_return_pct
            )
        units = (position.reported_market_value / position.anchor_unit_nav).quantize(
            QUANTITY_SCALE, rounding=ROUND_HALF_UP
        )
        nav_ratio = latest_unit_nav / position.anchor_unit_nav
        estimated_market = _money(units * latest_unit_nav)
        change = _money(estimated_market - position.reported_market_value)
        estimated_profit = _money(position.reported_profit_amount + change)
        estimated_return = (
            (Decimal("1") + position.reported_return_pct / Decimal("100")) * nav_ratio
            - Decimal("1")
        ) * Decimal("100")
        estimated_cumulative = (
            _money(position.reported_cumulative_profit_amount + change)
            if position.reported_cumulative_profit_amount is not None
            else None
        )
        daily_profit = (
            _money(units * (latest_unit_nav - previous_unit_nav))
            if previous_unit_nav is not None
            else None
        )
        estimated_cost_basis = None
        if estimated_return == 0:
            if estimated_profit == 0:
                estimated_cost_basis = estimated_market
        else:
            implied_cost = estimated_profit * Decimal("100") / estimated_return
            if implied_cost > 0:
                estimated_cost_basis = implied_cost
        conversion_rate = (
            Decimal("1")
            if position.currency == "CNY"
            else usd_cny_rate.rate
            if position.currency == "USD" and usd_cny_rate is not None
            else None
        )
        estimated_market_cny = (
            _money(estimated_market * conversion_rate) if conversion_rate is not None else None
        )
        estimated_profit_cny = (
            _money(estimated_profit * conversion_rate) if conversion_rate is not None else None
        )
        daily_profit_cny = (
            _money(daily_profit * conversion_rate)
            if daily_profit is not None and conversion_rate is not None
            else None
        )
        cost_basis_cny = (
            estimated_cost_basis * conversion_rate
            if estimated_cost_basis is not None and conversion_rate is not None
            else None
        )
        if estimated_market_cny is None or estimated_profit_cny is None:
            conversion_complete = False
        else:
            converted_market += estimated_market_cny
            converted_profit += estimated_profit_cny
        if daily_profit_cny is None:
            converted_daily_complete = False
        else:
            converted_daily_profit += daily_profit_cny
        if cost_basis_cny is None:
            converted_cost_complete = False
        else:
            converted_cost_basis += cost_basis_cny
        latest_fee = fees_by_share.get(position.fund_share_id)
        has_manual_override = any(
            value is not None
            for value in (
                position.manual_purchase_fee_pct,
                position.manual_management_fee_pct_annual,
                position.manual_custody_fee_pct_annual,
            )
        )
        management_fee = position.manual_management_fee_pct_annual
        if management_fee is None and latest_fee is not None:
            management_fee = latest_fee.management_fee_pct_annual
        custody_fee = position.manual_custody_fee_pct_annual
        if custody_fee is None and latest_fee is not None:
            custody_fee = latest_fee.custody_fee_pct_annual
        recurring_plan = None
        if (
            position.recurring_frequency == "DAILY"
            and position.recurring_gross_amount is not None
            and position.recurring_fee_pct is not None
            and position.recurring_net_amount is not None
        ):
            recurring_plan = PortfolioRecurringPlanRead(
                frequency="DAILY",
                gross_amount=position.recurring_gross_amount,
                fee_pct=position.recurring_fee_pct,
                net_amount=position.recurring_net_amount,
                currency=position.currency,
            )
        cash_flows = sorted(
            position.cash_flows,
            key=lambda item: (item.occurred_on or date(item.occurred_year, 1, 1), item.id),
        )
        result.append(
            PortfolioPositionRead(
                id=position.id,
                fund_id=position.fund_share.fund_contract_id,
                canonical_name=position.fund_share.fund_contract.canonical_name,
                manager_name=position.fund_share.fund_contract.manager_name,
                share_code=position.fund_share.share_code,
                platform=position.platform,
                currency=position.currency,
                snapshot_date=position.snapshot_date,
                reported_market_value=position.reported_market_value,
                reported_profit_amount=position.reported_profit_amount,
                reported_return_pct=position.reported_return_pct,
                reported_cumulative_profit_amount=position.reported_cumulative_profit_amount,
                anchor_nav_date=position.anchor_nav_date,
                anchor_unit_nav=position.anchor_unit_nav,
                estimated_units=units,
                latest_nav_date=latest_nav_date,
                latest_unit_nav=latest_unit_nav,
                latest_daily_return_pct=latest_daily_return,
                estimated_market_value=estimated_market,
                estimated_market_value_cny=estimated_market_cny,
                estimated_profit_amount=estimated_profit,
                estimated_profit_amount_cny=estimated_profit_cny,
                estimated_return_pct=estimated_return,
                estimated_cumulative_profit_amount=estimated_cumulative,
                estimated_daily_profit_amount=daily_profit,
                estimated_daily_profit_amount_cny=daily_profit_cny,
                change_since_snapshot=change,
                cash_dividend_total=_money(
                    sum((flow.amount for flow in cash_flows), start=Decimal("0"))
                ),
                cash_flows=[PortfolioCashFlowRead.model_validate(flow) for flow in cash_flows],
                recurring_plan=recurring_plan,
                fees=PortfolioFeeRead(
                    platform_purchase_fee_pct=position.manual_purchase_fee_pct,
                    standard_purchase_fee_pct=(
                        latest_fee.standard_purchase_fee_pct if latest_fee else None
                    ),
                    reference_discounted_purchase_fee_pct=(
                        latest_fee.discounted_purchase_fee_pct if latest_fee else None
                    ),
                    management_fee_pct_annual=management_fee,
                    custody_fee_pct_annual=custody_fee,
                    sales_service_fee_pct_annual=(
                        latest_fee.sales_service_fee_pct_annual if latest_fee else None
                    ),
                    source_provider=latest_fee.source_provider if latest_fee else None,
                    source_url=latest_fee.source_url if latest_fee else None,
                    snapshot_date=latest_fee.snapshot_date if latest_fee else None,
                    has_manual_override=has_manual_override,
                ),
                data_quality_note=position.data_quality_note,
            )
        )
        summary = summaries[position.currency]
        summary["position_count"] = int(summary["position_count"] or 0) + 1
        for key, value in (
            ("estimated_market_value", estimated_market),
            ("estimated_profit_amount", estimated_profit),
        ):
            summary[key] = Decimal(summary[key] or 0) + value
        if estimated_cost_basis is not None:
            summary["estimated_cost_basis"] = (
                Decimal(summary["estimated_cost_basis"] or 0) + estimated_cost_basis
            )
            summary["cost_basis_count"] = int(summary["cost_basis_count"] or 0) + 1
        if daily_profit is not None:
            summary["estimated_daily_profit_amount"] = (
                Decimal(summary["estimated_daily_profit_amount"] or 0) + daily_profit
            )
            summary["daily_profit_count"] = int(summary["daily_profit_count"] or 0) + 1
        if recurring_plan is not None:
            summary["recurring_gross_amount"] = (
                Decimal(summary["recurring_gross_amount"] or 0) + recurring_plan.gross_amount
            )
            summary["recurring_net_amount"] = (
                Decimal(summary["recurring_net_amount"] or 0) + recurring_plan.net_amount
            )

    currency_summaries: list[PortfolioCurrencySummaryRead] = []
    for currency, summary in sorted(summaries.items()):
        position_count = int(summary["position_count"] or 0)
        market_value = Decimal(summary["estimated_market_value"] or 0)
        profit_amount = Decimal(summary["estimated_profit_amount"] or 0)
        daily_profit_amount = Decimal(summary["estimated_daily_profit_amount"] or 0)
        recurring_gross = Decimal(summary["recurring_gross_amount"] or 0)
        recurring_net = Decimal(summary["recurring_net_amount"] or 0)
        currency_summaries.append(
            PortfolioCurrencySummaryRead(
                currency=currency,
                position_count=position_count,
                estimated_market_value=_money(market_value),
                estimated_profit_amount=_money(profit_amount),
                estimated_return_pct=(
                    _ratio_pct(profit_amount, Decimal(summary["estimated_cost_basis"] or 0))
                    if int(summary["cost_basis_count"] or 0) == position_count
                    else None
                ),
                estimated_daily_profit_amount=(
                    _money(daily_profit_amount)
                    if int(summary["daily_profit_count"] or 0) > 0
                    else None
                ),
                estimated_daily_return_pct=(
                    _ratio_pct(daily_profit_amount, market_value - daily_profit_amount)
                    if int(summary["daily_profit_count"] or 0) == position_count
                    else None
                ),
                recurring_gross_amount=_money(recurring_gross),
                recurring_net_amount=_money(recurring_net),
                recurring_net_pct=(
                    _ratio_pct(recurring_net, recurring_gross) if recurring_gross > 0 else None
                ),
            )
        )
    result.sort(key=lambda item: (item.platform, -item.estimated_market_value, item.share_code))
    converted_summary = (
        PortfolioConvertedSummaryRead(
            currency="CNY",
            estimated_market_value=_money(converted_market),
            estimated_profit_amount=_money(converted_profit),
            estimated_return_pct=(
                _ratio_pct(converted_profit, converted_cost_basis)
                if converted_cost_complete
                else None
            ),
            estimated_daily_profit_amount=(
                _money(converted_daily_profit) if converted_daily_complete else None
            ),
            estimated_daily_return_pct=(
                _ratio_pct(converted_daily_profit, converted_market - converted_daily_profit)
                if converted_daily_complete
                else None
            ),
            usd_cny_rate=usd_cny_rate.rate if usd_cny_rate is not None else None,
            rate_date=usd_cny_rate.rate_date if usd_cny_rate is not None else None,
            source_provider=(usd_cny_rate.source_provider if usd_cny_rate is not None else None),
            source_url=usd_cny_rate.source_url if usd_cny_rate is not None else None,
        )
        if conversion_complete
        else None
    )
    return PortfolioRead(
        latest_nav_date=max(item.latest_nav_date for item in result),
        positions=result,
        currency_summaries=currency_summaries,
        converted_summary=converted_summary,
    )


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _ratio_pct(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= 0:
        return None
    return (numerator / denominator * Decimal("100")).quantize(
        PERCENT_SCALE, rounding=ROUND_HALF_UP
    )


@router.get("/funds/{fund_id}", response_model=FundDetailRead)
def get_fund(fund_id: int, db: DbSession) -> FundDetailRead:
    fund = _get_fund(db, fund_id)
    summary = _fund_summaries(db, [fund])[0]
    assignments = db.scalars(
        select(FundExposureFamily)
        .where(FundExposureFamily.fund_contract_id == fund_id)
        .order_by(FundExposureFamily.id)
    ).all()
    families = [
        ExposureFamilyRead(
            code=item.exposure_family.code,
            display_name=item.exposure_family.display_name,
            description=item.exposure_family.description,
            report_id=item.fund_report_id,
            confidence=item.confidence,
            source_text=item.source_text,
        )
        for item in assignments
    ]
    return FundDetailRead(**summary.model_dump(), exposure_families=families)


@router.get("/funds/{fund_id}/shares", response_model=list[FundShareRead])
def list_fund_shares(fund_id: int, db: DbSession) -> list[FundShare]:
    _get_fund(db, fund_id)
    return list(
        db.scalars(
            select(FundShare)
            .where(FundShare.fund_contract_id == fund_id)
            .order_by(FundShare.share_code)
        ).all()
    )


@router.get("/funds/{fund_id}/reports", response_model=list[FundReportRead])
def list_fund_reports(fund_id: int, db: DbSession) -> list[FundReport]:
    _get_fund(db, fund_id)
    return list(
        db.scalars(
            select(FundReport)
            .where(FundReport.fund_contract_id == fund_id)
            .order_by(FundReport.period_end.desc(), FundReport.id.desc())
        ).all()
    )


@router.get("/funds/{fund_id}/purchase-limits", response_model=PurchaseLimitsRead)
def get_purchase_limits(
    fund_id: int,
    db: DbSession,
    share_code: str | None = None,
    snapshot_date: date | None = None,
    channel_type: PurchaseLimitChannel | None = None,
) -> PurchaseLimitsRead:
    """Return an exact day or the latest source-preserving snapshot per share."""

    _get_fund(db, fund_id)
    share_query = select(FundShare).where(FundShare.fund_contract_id == fund_id)
    if share_code:
        share_query = share_query.where(FundShare.share_code == share_code)
    shares = list(db.scalars(share_query.order_by(FundShare.share_code)).all())
    if share_code and not shares:
        raise HTTPException(status_code=404, detail="Share code not found for this fund")

    share_codes = {share.id: share.share_code for share in shares}
    if not share_codes:
        return PurchaseLimitsRead(fund_id=fund_id, items=[])

    filters: list[ColumnElement[bool]] = [DailyPurchaseLimit.fund_share_id.in_(share_codes)]
    if channel_type is not None:
        filters.append(DailyPurchaseLimit.channel_type == channel_type)

    query: Select[tuple[DailyPurchaseLimit]] = select(DailyPurchaseLimit)
    if snapshot_date is not None:
        query = query.where(*filters, DailyPurchaseLimit.snapshot_date == snapshot_date)
    else:
        latest_dates = (
            select(
                DailyPurchaseLimit.fund_share_id.label("fund_share_id"),
                func.max(DailyPurchaseLimit.snapshot_date).label("snapshot_date"),
            )
            .where(*filters)
            .group_by(DailyPurchaseLimit.fund_share_id)
            .subquery()
        )
        query = query.join(
            latest_dates,
            and_(
                DailyPurchaseLimit.fund_share_id == latest_dates.c.fund_share_id,
                DailyPurchaseLimit.snapshot_date == latest_dates.c.snapshot_date,
            ),
        ).where(*filters)

    rows = list(
        db.scalars(
            query.order_by(
                DailyPurchaseLimit.fund_share_id,
                DailyPurchaseLimit.snapshot_date.desc(),
                DailyPurchaseLimit.channel_type,
                DailyPurchaseLimit.channel_key,
                DailyPurchaseLimit.business_type,
                DailyPurchaseLimit.limit_basis,
                DailyPurchaseLimit.share_scope,
                DailyPurchaseLimit.source_provider,
                DailyPurchaseLimit.id,
            )
        ).all()
    )
    return PurchaseLimitsRead(
        fund_id=fund_id,
        items=[
            PurchaseLimitRead(
                id=row.id,
                fund_share_id=row.fund_share_id,
                share_code=share_codes[row.fund_share_id],
                snapshot_date=row.snapshot_date,
                channel_type=cast(PurchaseLimitChannel, row.channel_type),
                channel_key=row.channel_key,
                channel_name=row.channel_name,
                business_type=cast(
                    Literal["PURCHASE", "RECURRING_INVESTMENT", "CONVERSION_IN"],
                    row.business_type,
                ),
                availability_state=cast(
                    Literal["OPEN", "PAUSED", "UNKNOWN", "NOT_SOLD", "NOT_APPLICABLE"],
                    row.availability_state,
                ),
                cap_state=cast(Literal["LIMITED", "UNLIMITED", "UNKNOWN"], row.cap_state),
                daily_limit_amount=row.daily_limit_amount,
                currency=row.currency,
                limit_basis=cast(Literal["PER_ACCOUNT_PER_DAY", "UNKNOWN"], row.limit_basis),
                share_scope=cast(
                    Literal["PER_SHARE", "ALL_SHARES_COMBINED", "UNKNOWN"],
                    row.share_scope,
                ),
                effective_from=row.effective_from,
                effective_to=row.effective_to,
                source_provider=row.source_provider,
                source_url=row.source_url,
                source_published_at=row.source_published_at,
                fetched_at=row.fetched_at,
                source_artifact_id=row.source_artifact_id,
                raw_payload_hash=row.raw_payload_hash,
                raw_text=row.raw_text,
                confidence=row.confidence,
            )
            for row in rows
        ],
    )


@router.get("/funds/{fund_id}/country-exposure", response_model=ExposureRead)
def get_country_exposure(
    fund_id: int,
    db: DbSession,
    report_id: int | None = None,
    basis: str = "DIRECT",
) -> ExposureRead:
    normalized_basis = _normalize_basis(basis)
    report = _resolve_report(db, fund_id, report_id)
    items = (
        _allocation_items(db, ReportCountryAllocation, report.id, normalized_basis)
        if report
        else []
    )
    return ExposureRead(
        fund_id=fund_id,
        report_id=report.id if report else None,
        period_end=report.period_end if report else None,
        basis=normalized_basis,
        items=items,
    )


@router.get("/funds/{fund_id}/industry-exposure", response_model=ExposureRead)
def get_industry_exposure(
    fund_id: int,
    db: DbSession,
    report_id: int | None = None,
    basis: str = "DIRECT",
) -> ExposureRead:
    normalized_basis = _normalize_basis(basis)
    report = _resolve_report(db, fund_id, report_id)
    items = (
        _allocation_items(db, ReportIndustryAllocation, report.id, normalized_basis)
        if report
        else []
    )
    return ExposureRead(
        fund_id=fund_id,
        report_id=report.id if report else None,
        period_end=report.period_end if report else None,
        basis=normalized_basis,
        items=items,
    )


@router.get("/funds/{fund_id}/holdings", response_model=HoldingsRead)
def get_holdings(
    fund_id: int,
    db: DbSession,
    report_id: int | None = None,
    basis: str = "DIRECT",
) -> HoldingsRead:
    normalized_basis = _normalize_basis(basis)
    report = _resolve_report(db, fund_id, report_id)
    rows: list[ReportSecurityHolding] = []
    if report:
        rows = list(
            db.scalars(
                select(ReportSecurityHolding)
                .where(
                    ReportSecurityHolding.fund_report_id == report.id,
                    ReportSecurityHolding.exposure_basis == normalized_basis,
                )
                .order_by(
                    ReportSecurityHolding.rank.asc().nulls_last(),
                    ReportSecurityHolding.nav_pct.desc().nulls_last(),
                )
            ).all()
        )
    return HoldingsRead(
        fund_id=fund_id,
        report_id=report.id if report else None,
        period_end=report.period_end if report else None,
        basis=normalized_basis,
        items=[SecurityHoldingRead.model_validate(row) for row in rows],
    )


@router.get("/funds/{fund_id}/fund-holdings", response_model=FundHoldingsRead)
def get_fund_holdings(
    fund_id: int,
    db: DbSession,
    report_id: int | None = None,
    basis: str = "DIRECT",
) -> FundHoldingsRead:
    normalized_basis = _normalize_basis(basis)
    report = _resolve_report(db, fund_id, report_id)
    rows: list[ReportFundHolding] = []
    if report:
        rows = list(
            db.scalars(
                select(ReportFundHolding)
                .where(
                    ReportFundHolding.fund_report_id == report.id,
                    ReportFundHolding.exposure_basis == normalized_basis,
                )
                .order_by(
                    ReportFundHolding.rank.asc().nulls_last(),
                    ReportFundHolding.nav_pct.desc().nulls_last(),
                )
            ).all()
        )
    items = [
        FundHoldingRead(
            id=row.id,
            fund_code_raw=row.fund_code_raw,
            fund_name_raw=row.fund_name_raw,
            fund_name_normalized=row.fund_name_normalized,
            resolved_fund_contract_id=row.resolved_fund_contract_id,
            resolved_fund_name=(
                row.resolved_fund_contract.canonical_name if row.resolved_fund_contract else None
            ),
            currency=row.currency,
            fair_value_cny=row.fair_value_cny,
            nav_pct=row.nav_pct,
            rank=row.rank,
            is_unresolved=row.is_unresolved,
            exposure_basis=row.exposure_basis,
            source_section=row.source_section,
            raw_row=row.raw_row,
            parse_confidence=row.parse_confidence,
        )
        for row in rows
    ]
    return FundHoldingsRead(
        fund_id=fund_id,
        report_id=report.id if report else None,
        period_end=report.period_end if report else None,
        basis=normalized_basis,
        items=items,
    )


@router.get("/funds/{fund_id}/nav", response_model=NavHistoryRead)
def get_nav(
    fund_id: int,
    db: DbSession,
    share_code: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: Annotated[int, Query(ge=1, le=10000)] = 2000,
) -> NavHistoryRead:
    _get_fund(db, fund_id)
    share_query = select(FundShare).where(FundShare.fund_contract_id == fund_id)
    if share_code:
        share_query = share_query.where(FundShare.share_code == share_code)
    shares = list(db.scalars(share_query.order_by(FundShare.share_code)).all())
    if share_code and not shares:
        raise HTTPException(status_code=404, detail="Share code not found for this fund")
    share_codes = {share.id: share.share_code for share in shares}
    share_ids = list(share_codes)
    if not share_ids:
        return NavHistoryRead(fund_id=fund_id, items=[], exchange_prices=[])

    nav_query: Select[tuple[DailyFundNav]] = select(DailyFundNav).where(
        DailyFundNav.fund_share_id.in_(share_ids)
    )
    price_query: Select[tuple[DailyExchangePrice]] = select(DailyExchangePrice).where(
        DailyExchangePrice.fund_share_id.in_(share_ids)
    )
    if start_date:
        nav_query = nav_query.where(DailyFundNav.nav_date >= start_date)
        price_query = price_query.where(DailyExchangePrice.trade_date >= start_date)
    if end_date:
        nav_query = nav_query.where(DailyFundNav.nav_date <= end_date)
        price_query = price_query.where(DailyExchangePrice.trade_date <= end_date)

    nav_rows = list(
        db.scalars(
            nav_query.order_by(DailyFundNav.nav_date.desc(), DailyFundNav.fund_share_id).limit(
                limit
            )
        ).all()
    )
    price_rows = list(
        db.scalars(
            price_query.order_by(
                DailyExchangePrice.trade_date.desc(), DailyExchangePrice.fund_share_id
            ).limit(limit)
        ).all()
    )
    nav_rows.reverse()
    price_rows.reverse()
    return NavHistoryRead(
        fund_id=fund_id,
        items=[_nav_point(row, share_codes[row.fund_share_id]) for row in nav_rows],
        exchange_prices=[
            ExchangePriceRead(
                fund_share_id=row.fund_share_id,
                share_code=share_codes[row.fund_share_id],
                trade_date=row.trade_date,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                pct_change=row.pct_change,
                volume=row.volume,
                turnover=row.turnover,
                premium_discount_pct=row.premium_discount_pct,
                corresponding_nav_date=row.corresponding_nav_date,
                source_provider=row.source_provider,
                fetched_at=row.fetched_at,
            )
            for row in price_rows
        ],
    )


@router.get("/funds/{fund_id}/relations", response_model=list[FundRelationRead])
def get_relations(fund_id: int, db: DbSession) -> list[FundRelationRead]:
    _get_fund(db, fund_id)
    rows = db.scalars(
        select(FundRelation)
        .where(FundRelation.source_fund_contract_id == fund_id)
        .order_by(FundRelation.relation_type, FundRelation.id)
    ).all()
    return [
        FundRelationRead(
            id=row.id,
            source_fund_contract_id=row.source_fund_contract_id,
            target_fund_contract_id=row.target_fund_contract_id,
            target_fund_name=(
                row.target_fund_contract.canonical_name if row.target_fund_contract else None
            ),
            external_target_name=row.external_target_name,
            external_target_code=row.external_target_code,
            relation_type=row.relation_type,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            report_id=row.report_id,
            weight_nav_pct=row.weight_nav_pct,
            source_text=row.source_text,
            confidence=row.confidence,
        )
        for row in rows
    ]


def _selected_share(db: Session, fund: FundContract) -> FundShare | None:
    shares = db.scalars(
        select(FundShare)
        .where(FundShare.fund_contract_id == fund.id)
        .order_by(FundShare.share_code)
    ).all()
    return next(
        (share for share in shares if share.share_code == fund.representative_code),
        shares[0] if shares else None,
    )


def _pearson(left: dict[date, Decimal], right: dict[date, Decimal]) -> tuple[int, Decimal | None]:
    common = sorted(left.keys() & right.keys())
    if len(common) < 2:
        return len(common), None
    x = [float(left[item]) for item in common]
    y = [float(right[item]) for item in common]
    x_mean = sum(x) / len(x)
    y_mean = sum(y) / len(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y, strict=True))
    denominator = sqrt(sum((a - x_mean) ** 2 for a in x) * sum((b - y_mean) ** 2 for b in y))
    if denominator == 0:
        return len(common), None
    return len(common), Decimal(str(round(numerator / denominator, 8)))


@router.get("/compare", response_model=CompareRead)
def compare_funds(
    db: DbSession,
    fund_ids: Annotated[list[int], Query(min_length=2, max_length=5)],
    basis: str = "LOOKTHROUGH",
    nav_limit: Annotated[int, Query(ge=2, le=5000)] = 1000,
) -> CompareRead:
    normalized_basis = _normalize_basis(basis)
    unique_ids = list(dict.fromkeys(fund_ids))
    if len(unique_ids) != len(fund_ids):
        raise HTTPException(status_code=422, detail="fund_ids must be unique")
    funds = list(
        db.scalars(
            select(FundContract).where(FundContract.id.in_(unique_ids)).order_by(FundContract.id)
        ).all()
    )
    found_ids = {fund.id for fund in funds}
    missing = [fund_id for fund_id in unique_ids if fund_id not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail={"missing_fund_ids": missing})
    by_id = {fund.id: fund for fund in funds}
    ordered_funds = [by_id[fund_id] for fund_id in unique_ids]
    latest_reports = _latest_reports(db, unique_ids)

    exposures: list[CompareFundExposureRead] = []
    holdings_by_fund: dict[int, dict[str, ReportSecurityHolding]] = {}
    for fund_id in unique_ids:
        report = latest_reports.get(fund_id)
        if report is None:
            exposures.append(CompareFundExposureRead(fund_id=fund_id, country=[], industry=[]))
            holdings_by_fund[fund_id] = {}
            continue
        country = _allocation_items(db, ReportCountryAllocation, report.id, normalized_basis)
        industry = _allocation_items(db, ReportIndustryAllocation, report.id, normalized_basis)
        exposures.append(
            CompareFundExposureRead(fund_id=fund_id, country=country, industry=industry)
        )
        holding_rows = db.scalars(
            select(ReportSecurityHolding).where(
                ReportSecurityHolding.fund_report_id == report.id,
                ReportSecurityHolding.exposure_basis == normalized_basis,
            )
        ).all()
        keyed: dict[str, ReportSecurityHolding] = {}
        for row in holding_rows:
            code = (row.security_code_raw or "").strip().upper()
            key = f"CODE:{code}" if code else f"NAME:{row.security_name_normalized.casefold()}"
            keyed[key] = row
        holdings_by_fund[fund_id] = keyed

    overlaps: list[HoldingOverlapRead] = []
    for left_id, right_id in combinations(unique_ids, 2):
        left = holdings_by_fund[left_id]
        right = holdings_by_fund[right_id]
        items = []
        for key in sorted(left.keys() & right.keys()):
            left_row = left[key]
            right_row = right[key]
            items.append(
                OverlapSecurityRead(
                    security_code=left_row.security_code_raw or right_row.security_code_raw,
                    security_name=left_row.security_name_normalized,
                    left_nav_pct=left_row.nav_pct,
                    right_nav_pct=right_row.nav_pct,
                )
            )
        overlaps.append(
            HoldingOverlapRead(left_fund_id=left_id, right_fund_id=right_id, items=items)
        )

    nav_series: list[CompareNavSeriesRead] = []
    returns: dict[int, dict[date, Decimal]] = defaultdict(dict)
    for fund in ordered_funds:
        share = _selected_share(db, fund)
        if share is None:
            nav_series.append(CompareNavSeriesRead(fund_id=fund.id, share_code=None, items=[]))
            continue
        rows = list(
            db.scalars(
                select(DailyFundNav)
                .where(DailyFundNav.fund_share_id == share.id)
                .order_by(DailyFundNav.nav_date.desc())
                .limit(nav_limit)
            ).all()
        )
        rows.reverse()
        points = [_nav_point(row, share.share_code) for row in rows]
        nav_series.append(
            CompareNavSeriesRead(fund_id=fund.id, share_code=share.share_code, items=points)
        )
        for nav_row in rows:
            value = nav_row.calculated_daily_return_pct
            if value is None:
                value = nav_row.published_daily_return_pct
            if value is not None:
                returns[fund.id][nav_row.nav_date] = value

    correlations = []
    for left_id, right_id in combinations(unique_ids, 2):
        count, correlation = _pearson(returns[left_id], returns[right_id])
        correlations.append(
            ReturnCorrelationRead(
                left_fund_id=left_id,
                right_fund_id=right_id,
                common_observations=count,
                correlation=correlation,
            )
        )

    return CompareRead(
        funds=_fund_summaries(db, ordered_funds),
        exposure_basis=normalized_basis,
        exposures=exposures,
        holding_overlaps=overlaps,
        nav_series=nav_series,
        return_correlations=correlations,
    )


@router.get("/ingestion-runs", response_model=list[IngestionRunRead])
def list_ingestion_runs(
    db: DbSession,
    status: str | None = None,
    job_type: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[IngestionRun]:
    query = select(IngestionRun)
    if status:
        query = query.where(IngestionRun.status == status)
    if job_type:
        query = query.where(IngestionRun.job_type == job_type)
    return list(db.scalars(query.order_by(IngestionRun.started_at.desc()).limit(limit)).all())


@router.get("/data-quality-issues", response_model=list[DataQualityIssueRead])
def list_data_quality_issues(
    db: DbSession,
    status: str | None = None,
    severity: str | None = None,
    fund_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[dict[str, object]]:
    query = select(DataQualityIssue)
    if status:
        query = query.where(DataQualityIssue.status == status)
    if severity:
        query = query.where(DataQualityIssue.severity == severity)
    if fund_id is not None:
        query = query.where(DataQualityIssue.fund_contract_id == fund_id)
    issues = list(
        db.scalars(query.order_by(DataQualityIssue.detected_at.desc()).limit(limit)).all()
    )
    return _quality_issue_rows(db, issues)


def _quality_issue_rows(db: Session, issues: list[DataQualityIssue]) -> list[dict[str, object]]:
    """Add user-facing fund identity and traceable public sources to issue rows."""

    contract_ids = {item.fund_contract_id for item in issues if item.fund_contract_id}
    report_ids = {item.fund_report_id for item in issues if item.fund_report_id}
    share_ids = {item.fund_share_id for item in issues if item.fund_share_id}
    run_ids = {item.ingestion_run_id for item in issues if item.ingestion_run_id}

    reports = (
        {
            item.id: item
            for item in db.scalars(select(FundReport).where(FundReport.id.in_(report_ids)))
        }
        if report_ids
        else {}
    )
    shares = (
        {item.id: item for item in db.scalars(select(FundShare).where(FundShare.id.in_(share_ids)))}
        if share_ids
        else {}
    )
    contract_ids.update(item.fund_contract_id for item in reports.values())
    contract_ids.update(item.fund_contract_id for item in shares.values())
    contracts = (
        {
            item.id: item
            for item in db.scalars(select(FundContract).where(FundContract.id.in_(contract_ids)))
        }
        if contract_ids
        else {}
    )

    artifact_filters: list[ColumnElement[bool]] = []
    if contract_ids:
        artifact_filters.append(SourceArtifact.fund_contract_id.in_(contract_ids))
    if report_ids:
        artifact_filters.append(SourceArtifact.fund_report_id.in_(report_ids))
    if share_ids:
        artifact_filters.append(SourceArtifact.fund_share_id.in_(share_ids))
    if run_ids:
        artifact_filters.append(SourceArtifact.ingestion_run_id.in_(run_ids))
    artifacts = (
        list(
            db.scalars(
                select(SourceArtifact)
                .where(or_(*artifact_filters))
                .order_by(SourceArtifact.fetched_at.desc())
            )
        )
        if artifact_filters
        else []
    )

    rows: list[dict[str, object]] = []
    for issue in issues:
        report = reports.get(issue.fund_report_id) if issue.fund_report_id else None
        share = shares.get(issue.fund_share_id) if issue.fund_share_id else None
        fund_id = issue.fund_contract_id
        if fund_id is None and report is not None:
            fund_id = report.fund_contract_id
        if fund_id is None and share is not None:
            fund_id = share.fund_contract_id
        fund = contracts.get(fund_id) if fund_id else None
        urls = _urls_in_value(issue.details)
        if report is not None:
            urls.extend([report.source_page_url, report.document_url])
        for artifact in artifacts:
            if not _artifact_matches_issue(artifact, issue, fund_id):
                continue
            urls.append(artifact.source_url)
            urls.extend(_urls_in_value(artifact.metadata_json))
        rows.append(
            {
                **DataQualityIssueRead.model_validate(issue).model_dump(),
                "representative_code": fund.representative_code if fund else None,
                "fund_name": fund.canonical_name if fund else None,
                "source_urls": list(dict.fromkeys(url for url in urls if _is_public_url(url)))[:5],
            }
        )
    return rows


def _artifact_matches_issue(
    artifact: SourceArtifact, issue: DataQualityIssue, fund_id: int | None
) -> bool:
    if issue.issue_code.startswith("SALES_LIMIT_") and not artifact.artifact_type.startswith(
        "PURCHASE_LIMIT_"
    ):
        return False
    if issue.fund_report_id is not None:
        return artifact.fund_report_id == issue.fund_report_id
    if issue.fund_share_id is not None:
        return artifact.fund_share_id == issue.fund_share_id or (
            artifact.fund_share_id is None
            and artifact.fund_report_id is None
            and fund_id is not None
            and artifact.fund_contract_id == fund_id
        )
    if fund_id is not None:
        return artifact.fund_contract_id == fund_id
    return (
        issue.ingestion_run_id is not None and artifact.ingestion_run_id == issue.ingestion_run_id
    )


def _urls_in_value(value: object) -> list[str | None]:
    if isinstance(value, str):
        return [value] if _is_public_url(value) else []
    if isinstance(value, dict):
        urls: list[str | None] = []
        for item in value.values():
            urls.extend(_urls_in_value(item))
        return urls
    if isinstance(value, list):
        urls = []
        for item in value:
            urls.extend(_urls_in_value(item))
        return urls
    return []


def _is_public_url(value: object) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://"))
