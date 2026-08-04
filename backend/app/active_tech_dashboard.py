"""Request-time metrics for the active technology QDII dashboards."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date
from decimal import Decimal
from statistics import median
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    DailyFundNav,
    DataOperation,
    FundContract,
    FundReport,
    FundShare,
    ReportCountryAllocation,
)
from backend.app.period_returns import NavObservation, ReturnPeriod, calculate_period_return
from backend.app.schemas import (
    ActiveTechRegionAverageRead,
    ActiveTechRegionFundRead,
    ActiveTechRegionItemRead,
    ActiveTechRegionMissingRead,
    ActiveTechRegionsRead,
    ActiveTechReturnFundRead,
    ActiveTechReturnsRead,
    DashboardQuarterRead,
)

DashboardPool = Literal["CORE", "BROAD"]
ExposureBasis = Literal["DIRECT", "LOOKTHROUGH"]

ACTIVE_TECH_CORE_CODES = (
    "015884", "017653", "012379", "002891", "005698", "501312",
    "017436", "019265", "000988", "017429", "006373", "100055",
    "005699", "011420", "501225", "001668", "006555", "016701",
)
ACTIVE_TECH_DYNAMIC_CODES = (
    "012535", "519696", "000041", "013328", "017730", "019075",
    "007455", "486001", "486002", "019230", "270023", "012920",
    "018229", "519601", "080006",
)
ACTIVE_TECH_BROAD_CODES = ACTIVE_TECH_CORE_CODES + ACTIVE_TECH_DYNAMIC_CODES
STALE_NAV_AFTER_DAYS = 5

COUNTRY_LABELS = {
    "US": "美国",
    "UNITED STATES": "美国",
    "美国": "美国",
    "HK": "中国香港",
    "HONG KONG": "中国香港",
    "HONGKONG": "中国香港",
    "香港": "中国香港",
    "中国香港": "中国香港",
    "CN": "中国内地",
    "CHINA": "中国内地",
    "中国": "中国内地",
    "中国大陆": "中国内地",
    "KR": "韩国",
    "SOUTH KOREA": "韩国",
    "韩国": "韩国",
    "JP": "日本",
    "JAPAN": "日本",
    "日本": "日本",
    "TW": "中国台湾",
    "TAIWAN": "中国台湾",
    "台湾": "中国台湾",
    "中国台湾": "中国台湾",
}
REGION_CATEGORIES = (
    "美国",
    "日本",
    "韩国",
    "中国香港",
    "中国内地",
    "其他分类",
    "未披露",
)
PRIMARY_REGIONS = frozenset(REGION_CATEGORIES[:5])


def _pool_codes(pool: DashboardPool) -> tuple[str, ...]:
    return ACTIVE_TECH_CORE_CODES if pool == "CORE" else ACTIVE_TECH_BROAD_CODES


def _funds(db: Session, pool: DashboardPool) -> list[FundContract]:
    order = {code: index for index, code in enumerate(_pool_codes(pool))}
    funds = list(
        db.scalars(
            select(FundContract).where(
                FundContract.is_user_selected.is_(True),
                FundContract.representative_code.in_(_pool_codes(pool)),
            )
        ).all()
    )
    return sorted(funds, key=lambda fund: order[fund.representative_code])


def _shares_by_fund(db: Session, funds: Sequence[FundContract]) -> dict[int, FundShare]:
    fund_ids = [fund.id for fund in funds]
    if not fund_ids:
        return {}
    shares = list(
        db.scalars(
            select(FundShare)
            .where(FundShare.fund_contract_id.in_(fund_ids))
            .order_by(FundShare.fund_contract_id, FundShare.share_code)
        ).all()
    )
    by_fund: dict[int, list[FundShare]] = defaultdict(list)
    for share in shares:
        by_fund[share.fund_contract_id].append(share)

    selected: dict[int, FundShare] = {}
    for fund in funds:
        candidates = by_fund.get(fund.id, [])
        if not candidates:
            continue
        representative = next(
            (share for share in candidates if share.share_code == fund.representative_code),
            None,
        )
        selected[fund.id] = representative or min(
            candidates,
            key=lambda share: (
                share.currency != "CNY",
                share.is_exchange_traded,
                (share.share_class or "").upper() != "A",
                share.share_code,
            ),
        )
    return selected


def _sync_date(db: Session) -> date | None:
    operation = db.scalar(
        select(DataOperation)
        .where(
            DataOperation.operation == "sync-daily",
            DataOperation.status.in_(("succeeded", "partial")),
            DataOperation.finished_at.is_not(None),
        )
        .order_by(DataOperation.finished_at.desc(), DataOperation.id.desc())
        .limit(1)
    )
    if operation is None or operation.finished_at is None:
        return None
    finished_at = operation.finished_at
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=UTC)
    return finished_at.astimezone(ZoneInfo("Asia/Shanghai")).date()


def active_tech_returns(
    db: Session,
    *,
    pool: DashboardPool,
    period: ReturnPeriod,
    as_of: date,
) -> ActiveTechReturnsRead:
    funds = _funds(db, pool)
    shares = _shares_by_fund(db, funds)
    share_ids = [share.id for share in shares.values()]
    nav_rows = list(
        db.scalars(
            select(DailyFundNav)
            .where(
                DailyFundNav.fund_share_id.in_(share_ids),
                DailyFundNav.nav_date <= as_of,
            )
            .order_by(DailyFundNav.fund_share_id, DailyFundNav.nav_date, DailyFundNav.id)
        ).all()
    ) if share_ids else []
    navs_by_share: dict[int, dict[date, DailyFundNav]] = defaultdict(dict)
    for row in nav_rows:
        navs_by_share[row.fund_share_id][row.nav_date] = row

    latest_by_fund = {
        fund.id: max(navs_by_share[share.id])
        for fund in funds
        if (share := shares.get(fund.id)) is not None and navs_by_share.get(share.id)
    }
    available_date_sets = [
        set(navs_by_share[share.id])
        for fund in funds
        if (share := shares.get(fund.id)) is not None and navs_by_share.get(share.id)
    ]
    common_dates = set.intersection(*available_date_sets) if available_date_sets else set()
    common_date = max(common_dates) if common_dates else None
    latest_official_date = max(latest_by_fund.values()) if latest_by_fund else None

    items: list[ActiveTechReturnFundRead] = []
    for fund in funds:
        share = shares.get(fund.id)
        latest_date = latest_by_fund.get(fund.id)
        if share is None or latest_date is None or common_date is None:
            items.append(
                ActiveTechReturnFundRead(
                    fund_id=fund.id,
                    representative_code=fund.representative_code,
                    fund_name=fund.canonical_name,
                    original_category=fund.original_category,
                    pool_segment=(
                        "CORE" if fund.representative_code in ACTIVE_TECH_CORE_CODES else "DYNAMIC"
                    ),
                    share_code=share.share_code if share else None,
                    return_pct=None,
                    baseline_date=None,
                    end_date=None,
                    latest_official_nav_date=latest_date,
                    nav_lag_days=(as_of - latest_date).days if latest_date else None,
                    uses_accumulated_nav=False,
                    status="MISSING_NAV",
                )
            )
            continue

        observations = [
            NavObservation(row.nav_date, row.unit_nav, row.accumulated_nav)
            for row in navs_by_share[share.id].values()
        ]
        result = calculate_period_return(
            observations,
            period=period,
            end_date=common_date,
            period_as_of=as_of,
        )
        lag_days = (as_of - latest_date).days
        status = (
            "STALE"
            if result.status == "READY" and lag_days > STALE_NAV_AFTER_DAYS
            else result.status
        )
        items.append(
            ActiveTechReturnFundRead(
                fund_id=fund.id,
                representative_code=fund.representative_code,
                fund_name=fund.canonical_name,
                original_category=fund.original_category,
                pool_segment=(
                    "CORE" if fund.representative_code in ACTIVE_TECH_CORE_CODES else "DYNAMIC"
                ),
                share_code=share.share_code,
                return_pct=result.return_pct,
                baseline_date=result.baseline_date,
                end_date=result.end_date,
                latest_official_nav_date=latest_date,
                nav_lag_days=lag_days,
                uses_accumulated_nav=result.uses_accumulated_nav,
                status=status,
            )
        )

    comparable = [item.return_pct for item in items if item.return_pct is not None]
    return ActiveTechReturnsRead(
        pool=pool,
        period=period,
        as_of=as_of,
        sync_date=_sync_date(db),
        latest_official_nav_date=latest_official_date,
        common_comparable_date=common_date,
        configured_fund_count=len(_pool_codes(pool)),
        fund_count=len(funds),
        comparable_fund_count=len(comparable),
        missing_fund_count=sum(
            item.status in {"MISSING_NAV", "MISSING_BASELINE"} for item in items
        ),
        stale_fund_count=sum(item.status == "STALE" for item in items),
        positive_fund_count=sum(value > 0 for value in comparable),
        negative_fund_count=sum(value < 0 for value in comparable),
        average_return_pct=(
            sum(comparable, Decimal("0")) / len(comparable) if comparable else None
        ),
        median_return_pct=median(comparable) if comparable else None,
        items=items,
    )


def _quarter_options(db: Session, fund_ids: Sequence[int]) -> list[DashboardQuarterRead]:
    if not fund_ids:
        return []
    rows = db.execute(
        select(FundReport.report_year, FundReport.report_quarter, FundReport.period_end)
        .where(
            FundReport.fund_contract_id.in_(fund_ids),
            FundReport.report_type == "QUARTERLY",
            FundReport.report_quarter.is_not(None),
        )
        .distinct()
        .order_by(FundReport.report_year.desc(), FundReport.report_quarter.desc())
    ).all()
    options: dict[tuple[int, int], date] = {}
    for year, quarter, period_end in rows:
        if quarter is not None:
            options.setdefault((year, quarter), period_end)
    return [
        DashboardQuarterRead(year=year, quarter=quarter, period_end=period_end)
        for (year, quarter), period_end in options.items()
    ]


def _country_label(value: str) -> str:
    normalized = value.strip()
    return COUNTRY_LABELS.get(normalized.upper(), normalized)


def _dashboard_region(value: str) -> str:
    label = _country_label(value)
    return label if label in PRIMARY_REGIONS else "其他分类"


def active_tech_regions(
    db: Session,
    *,
    pool: DashboardPool,
    basis: ExposureBasis,
    year: int | None,
    quarter: int | None,
) -> ActiveTechRegionsRead:
    funds = _funds(db, pool)
    fund_ids = [fund.id for fund in funds]
    available_quarters = _quarter_options(db, fund_ids)
    if (year is None) != (quarter is None):
        raise ValueError("year and quarter must be provided together")
    if year is None and available_quarters:
        year = available_quarters[0].year
        quarter = available_quarters[0].quarter

    reports = list(
        db.scalars(
            select(FundReport).where(
                FundReport.fund_contract_id.in_(fund_ids),
                FundReport.report_type == "QUARTERLY",
                FundReport.report_year == year,
                FundReport.report_quarter == quarter,
            )
        ).all()
    ) if fund_ids and year is not None and quarter is not None else []
    reports_by_fund = {report.fund_contract_id: report for report in reports}
    report_ids = [report.id for report in reports]
    rows = list(
        db.scalars(
            select(ReportCountryAllocation)
            .where(
                ReportCountryAllocation.fund_report_id.in_(report_ids),
                ReportCountryAllocation.exposure_basis == basis,
                ReportCountryAllocation.nav_pct.is_not(None),
            )
            .order_by(ReportCountryAllocation.fund_report_id, ReportCountryAllocation.rank)
        ).all()
    ) if report_ids else []
    allocations_by_report: dict[int, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in rows:
        country = _dashboard_region(row.country_name_normalized)
        allocations_by_report[row.fund_report_id][country] += row.nav_pct or Decimal("0")

    covered: list[ActiveTechRegionFundRead] = []
    missing: list[ActiveTechRegionMissingRead] = []
    country_totals: dict[str, Decimal] = defaultdict(Decimal)
    for fund in funds:
        report = reports_by_fund.get(fund.id)
        if report is None:
            missing.append(
                ActiveTechRegionMissingRead(
                    fund_id=fund.id,
                    representative_code=fund.representative_code,
                    fund_name=fund.canonical_name,
                    reason="MISSING_REPORT",
                )
            )
            continue
        if (report.parse_status or "").strip().lower() != "parsed":
            missing.append(
                ActiveTechRegionMissingRead(
                    fund_id=fund.id,
                    representative_code=fund.representative_code,
                    fund_name=fund.canonical_name,
                    reason="REPORT_NOT_PARSED",
                )
            )
            continue
        allocations = allocations_by_report.get(report.id, {})
        if not allocations:
            missing.append(
                ActiveTechRegionMissingRead(
                    fund_id=fund.id,
                    representative_code=fund.representative_code,
                    fund_name=fund.canonical_name,
                    reason="MISSING_EXPOSURE",
                )
            )
            continue
        disclosed_country_pct = sum(allocations.values(), Decimal("0"))
        undisclosed_pct = max(Decimal("0"), Decimal("100") - disclosed_country_pct)
        grouped_allocations = {
            country: (
                undisclosed_pct if country == "未披露" else allocations.get(country, Decimal("0"))
            )
            for country in REGION_CATEGORIES
        }
        items = [
            ActiveTechRegionItemRead(country=country, nav_pct=grouped_allocations[country])
            for country in REGION_CATEGORIES
        ]
        for item in items:
            country_totals[item.country] += item.nav_pct
        covered.append(
            ActiveTechRegionFundRead(
                fund_id=fund.id,
                representative_code=fund.representative_code,
                fund_name=fund.canonical_name,
                pool_segment=(
                    "CORE" if fund.representative_code in ACTIVE_TECH_CORE_CODES else "DYNAMIC"
                ),
                report_id=report.id,
                report_period_end=report.period_end,
                parse_confidence=report.parse_confidence,
                disclosed_country_pct=disclosed_country_pct,
                allocations=items,
            )
        )

    denominator = Decimal(len(covered)) if covered else None
    averages = [
        ActiveTechRegionAverageRead(
            country=country,
            average_nav_pct=total / denominator,
            covered_fund_count=sum(
                any(item.country == country and item.nav_pct > 0 for item in fund.allocations)
                for fund in covered
            ),
        )
        for country in REGION_CATEGORIES
        if denominator is not None
        for total in (country_totals[country],)
    ]
    selected_period_end = next(
        (
            option.period_end
            for option in available_quarters
            if option.year == year and option.quarter == quarter
        ),
        None,
    )
    return ActiveTechRegionsRead(
        pool=pool,
        basis=basis,
        report_year=year,
        report_quarter=quarter,
        period_end=selected_period_end,
        sync_date=_sync_date(db),
        configured_fund_count=len(_pool_codes(pool)),
        fund_count=len(funds),
        covered_fund_count=len(covered),
        missing_fund_count=len(missing),
        available_quarters=available_quarters,
        average_distribution=averages,
        funds=covered,
        missing=missing,
    )
