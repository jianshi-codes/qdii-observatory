"""Explicit, bounded data-preparation operations shared by the local API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.ingestion.fx_pipeline import sync_exchange_rates
from backend.app.ingestion.limit_pipeline import sync_purchase_limits
from backend.app.ingestion.lookthrough import calculate_and_store_lookthrough
from backend.app.ingestion.nav_pipeline import sync_daily
from backend.app.ingestion.provider_registry import provider_client
from backend.app.ingestion.providers.fx import EcbExchangeRateProvider
from backend.app.ingestion.providers.limits import (
    CsrcPurchaseLimitProvider,
    EastmoneyPurchaseLimitProvider,
)
from backend.app.ingestion.providers.market import EastmoneyMarketPriceProvider
from backend.app.ingestion.providers.nav import EastmoneyNavProvider
from backend.app.ingestion.providers.reports import CsrcReportProvider
from backend.app.ingestion.report_pipeline import parse_reports, sync_reports
from backend.app.models import (
    DailyFundNav,
    DailyPurchaseLimit,
    FundContract,
    FundReport,
    FundShare,
    IngestionRun,
    ReportDerivedMetrics,
)


class NoSelectedFundsError(RuntimeError):
    """The operation requires at least one imported user fund."""


class UnknownFundCodesError(ValueError):
    def __init__(self, codes: set[str]):
        self.codes = tuple(sorted(codes))
        super().__init__(f"fund codes are not in the imported universe: {list(self.codes)}")


@dataclass(frozen=True, slots=True)
class DataOperationResult:
    operation: str
    status: str
    fund_codes: tuple[str, ...]
    runs: tuple[IngestionRun, ...]
    report_year: int | None = None
    report_quarter: int | None = None
    lookthrough_reports: int | None = None


@dataclass(frozen=True, slots=True)
class DataPreparationStatus:
    total_funds: int
    total_shares: int
    nav_ready_funds: int
    latest_nav_date: date | None
    limit_ready_funds: int
    latest_limit_snapshot_date: date | None
    report_year: int
    report_quarter: int
    report_downloaded_funds: int
    report_parsed_funds: int
    lookthrough_ready_funds: int


def latest_completed_quarter(today: date | None = None) -> tuple[int, int]:
    current = today or date.today()
    current_quarter = (current.month - 1) // 3 + 1
    if current_quarter == 1:
        return current.year - 1, 4
    return current.year, current_quarter - 1


def selected_fund_codes(
    session: Session,
    requested_codes: set[str] | None = None,
) -> tuple[str, ...]:
    rows = session.execute(
        select(FundContract.representative_code, FundShare.share_code)
        .join(FundShare, FundShare.fund_contract_id == FundContract.id)
        .where(FundContract.is_user_selected.is_(True))
    ).all()
    code_to_representative = {
        code: representative
        for representative, share_code in rows
        for code in (representative, share_code)
    }
    available = set(code_to_representative.values())
    if not available:
        raise NoSelectedFundsError("import at least one fund before preparing data")
    if requested_codes:
        missing = requested_codes - code_to_representative.keys()
        if missing:
            raise UnknownFundCodesError(missing)
        return tuple(sorted({code_to_representative[code] for code in requested_codes}))
    return tuple(sorted(available))


def share_codes_for_funds(session: Session, fund_codes: tuple[str, ...]) -> set[str]:
    return set(
        session.scalars(
            select(FundShare.share_code)
            .join(FundContract, FundShare.fund_contract_id == FundContract.id)
            .where(
                FundContract.is_user_selected.is_(True),
                FundContract.representative_code.in_(fund_codes),
            )
        ).all()
    )


def sync_daily_data(
    session: Session,
    raw_root: Path,
    *,
    fund_codes: tuple[str, ...],
    lookback_days: int = 10,
) -> DataOperationResult:
    share_codes = share_codes_for_funds(session, fund_codes)
    with provider_client("eastmoney_nav", "eastmoney_market", "csrc_reports", "ecb_fx") as http:
        nav_run, market_run = sync_daily(
            session,
            EastmoneyNavProvider(http),
            EastmoneyMarketPriceProvider(http),
            raw_root,
            lookback_days=lookback_days,
            share_codes=share_codes,
        )
        limit_run = sync_purchase_limits(
            session,
            CsrcPurchaseLimitProvider(http),
            EastmoneyPurchaseLimitProvider(http),
            raw_root,
            fund_codes=set(fund_codes),
        )
        fx_run = sync_exchange_rates(session, EcbExchangeRateProvider(http), raw_root)
    runs = (nav_run, market_run, limit_run, fx_run)
    return DataOperationResult(
        operation="sync_daily",
        status=_combined_status(runs),
        fund_codes=fund_codes,
        runs=runs,
    )


def sync_sales_limits_data(
    session: Session,
    raw_root: Path,
    *,
    fund_codes: tuple[str, ...],
) -> DataOperationResult:
    with provider_client("csrc_reports") as http:
        run = sync_purchase_limits(
            session,
            CsrcPurchaseLimitProvider(http),
            EastmoneyPurchaseLimitProvider(http),
            raw_root,
            fund_codes=set(fund_codes),
        )
    return DataOperationResult(
        operation="sync_sales_limits",
        status=run.status,
        fund_codes=fund_codes,
        runs=(run,),
    )


def sync_reports_data(
    session: Session,
    raw_root: Path,
    *,
    fund_codes: tuple[str, ...],
    year: int,
    quarter: int,
) -> DataOperationResult:
    with provider_client("csrc_reports") as http:
        run = sync_reports(
            session,
            CsrcReportProvider(http),
            raw_root,
            year=year,
            quarter=quarter,
            representative_codes=set(fund_codes),
        )
    return DataOperationResult(
        operation="sync_reports",
        status=run.status,
        fund_codes=fund_codes,
        runs=(run,),
        report_year=year,
        report_quarter=quarter,
    )


def parse_reports_data(
    session: Session,
    raw_root: Path,
    *,
    fund_codes: tuple[str, ...],
    year: int,
    quarter: int,
) -> DataOperationResult:
    run = parse_reports(
        session,
        raw_root,
        year=year,
        quarter=quarter,
        representative_codes=set(fund_codes),
    )
    lookthrough = calculate_and_store_lookthrough(session, year=year, quarter=quarter)
    session.commit()
    return DataOperationResult(
        operation="parse_reports",
        status=run.status,
        fund_codes=fund_codes,
        runs=(run,),
        report_year=year,
        report_quarter=quarter,
        lookthrough_reports=len(lookthrough),
    )


def prepare_data(
    session: Session,
    raw_root: Path,
    *,
    fund_codes: tuple[str, ...],
    year: int,
    quarter: int,
    lookback_days: int = 10,
) -> DataOperationResult:
    daily = sync_daily_data(
        session,
        raw_root,
        fund_codes=fund_codes,
        lookback_days=lookback_days,
    )
    reports = sync_reports_data(
        session,
        raw_root,
        fund_codes=fund_codes,
        year=year,
        quarter=quarter,
    )
    parsed = parse_reports_data(
        session,
        raw_root,
        fund_codes=fund_codes,
        year=year,
        quarter=quarter,
    )
    runs = (*daily.runs, *reports.runs, *parsed.runs)
    return DataOperationResult(
        operation="prepare_data",
        status=_combined_status(runs),
        fund_codes=fund_codes,
        runs=runs,
        report_year=year,
        report_quarter=quarter,
        lookthrough_reports=parsed.lookthrough_reports,
    )


def preparation_status(session: Session, *, today: date | None = None) -> DataPreparationStatus:
    year, quarter = latest_completed_quarter(today)
    fund_ids = set(
        session.scalars(
            select(FundContract.id).where(FundContract.is_user_selected.is_(True))
        ).all()
    )
    total_shares = session.scalar(
        select(func.count(FundShare.id)).where(FundShare.fund_contract_id.in_(fund_ids))
    )
    nav_fund_ids = set(
        session.scalars(
            select(FundShare.fund_contract_id)
            .join(DailyFundNav, DailyFundNav.fund_share_id == FundShare.id)
            .where(FundShare.fund_contract_id.in_(fund_ids))
            .distinct()
        ).all()
    )
    limit_fund_ids = set(
        session.scalars(
            select(FundShare.fund_contract_id)
            .join(DailyPurchaseLimit, DailyPurchaseLimit.fund_share_id == FundShare.id)
            .where(FundShare.fund_contract_id.in_(fund_ids))
            .distinct()
        ).all()
    )
    reports = list(
        session.scalars(
            select(FundReport).where(
                FundReport.fund_contract_id.in_(fund_ids),
                FundReport.report_type == "QUARTERLY",
                FundReport.report_year == year,
                FundReport.report_quarter == quarter,
            )
        ).all()
    )
    downloaded = {report.fund_contract_id for report in reports if report.local_document_path}
    parsed = {
        report.fund_contract_id
        for report in reports
        if report.parse_status.lower() in {"parsed", "valid_empty"}
    }
    report_ids = [report.id for report in reports]
    lookthrough_report_ids = set(
        session.scalars(
            select(ReportDerivedMetrics.fund_report_id).where(
                ReportDerivedMetrics.fund_report_id.in_(report_ids),
                ReportDerivedMetrics.lookthrough_coverage_pct.is_not(None),
            )
        ).all()
    )
    return DataPreparationStatus(
        total_funds=len(fund_ids),
        total_shares=int(total_shares or 0),
        nav_ready_funds=len(nav_fund_ids),
        latest_nav_date=session.scalar(
            select(func.max(DailyFundNav.nav_date))
            .join(FundShare, DailyFundNav.fund_share_id == FundShare.id)
            .where(FundShare.fund_contract_id.in_(fund_ids))
        ),
        limit_ready_funds=len(limit_fund_ids),
        latest_limit_snapshot_date=session.scalar(
            select(func.max(DailyPurchaseLimit.snapshot_date))
            .join(FundShare, DailyPurchaseLimit.fund_share_id == FundShare.id)
            .where(FundShare.fund_contract_id.in_(fund_ids))
        ),
        report_year=year,
        report_quarter=quarter,
        report_downloaded_funds=len(downloaded),
        report_parsed_funds=len(parsed),
        lookthrough_ready_funds=len(lookthrough_report_ids),
    )


def _combined_status(runs: tuple[IngestionRun, ...]) -> str:
    statuses = {run.status.lower() for run in runs}
    if statuses == {"succeeded"}:
        return "succeeded"
    if statuses == {"failed"}:
        return "failed"
    return "partial"
