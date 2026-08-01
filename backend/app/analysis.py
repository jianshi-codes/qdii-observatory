"""Transparent disclosed-holdings consistency baseline."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from math import sqrt
from pathlib import Path
from typing import Literal

import yaml
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.models import DailyFundNav, FundContract, FundReport, FundShare

MODEL_NAME = "DISCLOSED_HOLDINGS_BASELINE"
AnalysisStatus = Literal[
    "CONSISTENT",
    "SLIGHTLY_DIVERGING",
    "LIKELY_EXPOSURE_CHANGED",
    "INSUFFICIENT_DATA",
    "NOT_APPLICABLE",
]


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    model: str
    fund_code: str
    report_year: int
    report_quarter: int | None
    report_period_end: date
    report_public_available_at: date | None
    analysis_start_date: date
    mode: str
    coverage: Decimal
    observations: int
    residual_mean_pct: Decimal | None
    mae_pct: Decimal | None
    bias_pct: Decimal | None
    correlation: Decimal | None
    consistency_status: AnalysisStatus
    undisclosed_equity_pct: Decimal | None
    unresolved_fund_weight_pct: Decimal | None
    limitation: str


def analyze_disclosed_holdings(
    session: Session,
    *,
    fund_code: str,
    proxy_config: Path,
    year: int | None = None,
    quarter: int | None = None,
    latest_report: bool = False,
) -> AnalysisResult:
    fund = session.scalar(
        select(FundContract)
        .join(FundShare, FundShare.fund_contract_id == FundContract.id)
        .where(
            or_(FundContract.representative_code == fund_code, FundShare.share_code == fund_code)
        )
    )
    if fund is None:
        raise ValueError(f"fund code not found: {fund_code}")
    report_query = select(FundReport).where(FundReport.fund_contract_id == fund.id)
    if latest_report:
        report_query = report_query.order_by(FundReport.period_end.desc(), FundReport.id.desc())
    else:
        if year is None or quarter is None:
            raise ValueError("provide --year and --quarter, or --latest-report")
        report_query = report_query.where(
            FundReport.report_year == year,
            FundReport.report_quarter == quarter,
        )
    report = session.scalar(report_query)
    if report is None:
        raise ValueError("matching parsed report not found")
    start = report.period_end + timedelta(days=1)
    public_date = report.public_available_at.date() if report.public_available_at else None
    mode = "EX_POST" if public_date is not None and start < public_date else "LIVE_AVAILABLE"
    status: AnalysisStatus = "INSUFFICIENT_DATA"
    strategy = (fund.strategy_type or "").upper()
    if "主动" not in strategy and "ACTIVE" not in strategy:
        status = "NOT_APPLICABLE"
    actual = _actual_returns(session, fund, start)
    estimated = _estimated_returns(proxy_config, fund.representative_code)
    dates = sorted(actual.keys() & estimated.keys())
    coverage = Decimal(len(dates)) / Decimal(len(actual)) if actual else Decimal("0")
    residuals = [actual[item] - estimated[item] for item in dates]
    mae = _mean([abs(value) for value in residuals])
    bias = _mean(residuals)
    correlation = _correlation(
        [actual[item] for item in dates], [estimated[item] for item in dates]
    )
    if status != "NOT_APPLICABLE":
        status = _status(len(dates), mae, correlation)
    metrics = report.derived_metrics
    return AnalysisResult(
        model=MODEL_NAME,
        fund_code=fund.representative_code,
        report_year=report.report_year,
        report_quarter=report.report_quarter,
        report_period_end=report.period_end,
        report_public_available_at=public_date,
        analysis_start_date=start,
        mode=mode,
        coverage=coverage.quantize(Decimal("0.0001")),
        observations=len(dates),
        residual_mean_pct=_quantize(bias),
        mae_pct=_quantize(mae),
        bias_pct=_quantize(bias),
        correlation=_quantize(correlation),
        consistency_status=status,
        undisclosed_equity_pct=metrics.undisclosed_equity_pct if metrics else None,
        unresolved_fund_weight_pct=metrics.unresolved_fund_weight_pct if metrics else None,
        limitation=(
            "This baseline explains disclosed holdings only; it cannot identify "
            "actual trades or produce investment instructions."
        ),
    )


def export_evidence(result: AnalysisResult, output_dir: Path, mode: str = "REDACTED") -> Path:
    normalized = mode.upper()
    if normalized not in {"PUBLIC", "REDACTED", "PRIVATE"}:
        raise ValueError("export mode must be PUBLIC, REDACTED, or PRIVATE")
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = asdict(result)
    payload["export_mode"] = normalized
    if normalized == "PUBLIC":
        payload["fund_code"] = "REDACTED"
    path = output_dir / (
        f"{result.fund_code}-{result.report_year}q{result.report_quarter or 0}-"
        f"{normalized.lower()}.json"
    )
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return path


def _actual_returns(session: Session, fund: FundContract, start: date) -> dict[date, Decimal]:
    rows = session.execute(
        select(
            DailyFundNav.nav_date,
            DailyFundNav.published_daily_return_pct,
            DailyFundNav.calculated_daily_return_pct,
        )
        .join(FundShare, FundShare.id == DailyFundNav.fund_share_id)
        .where(FundShare.share_code == fund.representative_code, DailyFundNav.nav_date >= start)
        .order_by(DailyFundNav.nav_date)
    ).all()
    return {
        nav_date: published if published is not None else calculated
        for nav_date, published, calculated in rows
        if published is not None or calculated is not None
    }


def _estimated_returns(config_path: Path, fund_code: str) -> dict[date, Decimal]:
    if not config_path.is_file():
        return {}
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config = (payload.get("funds") or {}).get(fund_code) or {}
    series_path = config.get("estimated_returns_file")
    if not series_path:
        return {}
    path = Path(series_path)
    if not path.is_absolute():
        path = config_path.parent.parent / path
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        return {
            date.fromisoformat(row["date"]): Decimal(row["estimated_return_pct"]) for row in rows
        }


def _mean(values: list[Decimal]) -> Decimal | None:
    return sum(values, Decimal("0")) / Decimal(len(values)) if values else None


def _correlation(left: list[Decimal], right: list[Decimal]) -> Decimal | None:
    if len(left) < 2:
        return None
    left_mean = _mean(left)
    right_mean = _mean(right)
    assert left_mean is not None and right_mean is not None
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    left_scale = sqrt(float(sum((x - left_mean) ** 2 for x in left)))
    right_scale = sqrt(float(sum((y - right_mean) ** 2 for y in right)))
    if left_scale == 0 or right_scale == 0:
        return None
    return Decimal(str(float(numerator) / (left_scale * right_scale)))


def _status(count: int, mae: Decimal | None, correlation: Decimal | None) -> AnalysisStatus:
    if count < 5 or mae is None or correlation is None:
        return "INSUFFICIENT_DATA"
    if correlation >= Decimal("0.90") and mae <= Decimal("0.50"):
        return "CONSISTENT"
    if correlation >= Decimal("0.70") and mae <= Decimal("1.00"):
        return "SLIGHTLY_DIVERGING"
    return "LIKELY_EXPOSURE_CHANGED"


def _quantize(value: Decimal | None) -> Decimal | None:
    return value.quantize(Decimal("0.0001")) if value is not None else None
