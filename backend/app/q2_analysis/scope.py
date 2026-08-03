"""Fail-closed selection of active-fund analysis targets."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from backend.app.models import (
    FundContract,
    FundReport,
    FundShare,
    PortfolioPosition,
    ReportSecurityHolding,
)
from backend.app.q2_analysis import ANALYSIS_START_DATE

Q2_PERIOD_END: Final = date(2026, 6, 30)
ACTIVE_WRAPPER: Final = "DIRECT"


class AnalysisScopeError(ValueError):
    """Raised when an analysis request would escape the supported scope."""


@dataclass(frozen=True, slots=True)
class AnalysisTarget:
    fund_id: int
    fund_name: str
    representative_code: str
    strategy_type: str | None
    wrapper_type: str | None
    tech_scope: str
    share_id: int
    share_code: str
    share_currency: str
    report_id: int


def validate_analysis_dates(start_date: date, as_of: date) -> None:
    if start_date < ANALYSIS_START_DATE:
        raise AnalysisScopeError(
            f"start_date must not be earlier than {ANALYSIS_START_DATE.isoformat()}"
        )
    if as_of < start_date:
        raise AnalysisScopeError("as_of must be on or after start_date")


def select_portfolio_active_funds(session: Session) -> list[AnalysisTarget]:
    """Select only active position shares; never begin from the fund universe."""

    rows = session.execute(
        _eligible_target_query()
        .join(PortfolioPosition, PortfolioPosition.fund_share_id == FundShare.id)
        .where(PortfolioPosition.is_active.is_(True))
        .order_by(FundContract.representative_code, FundShare.share_code)
    ).all()
    targets = _targets_from_rows(rows)
    if not targets:
        raise AnalysisScopeError("No active funds with Q2 direct stock holdings in portfolio")
    return targets


def select_explicit_active_fund(session: Session, fund_code: str) -> AnalysisTarget:
    """Resolve one explicitly requested share/representative code without a full scan."""

    _validate_fund_code(fund_code)
    rows = session.execute(
        _eligible_target_query()
        .where(
            or_(
                FundShare.share_code == fund_code,
                FundContract.representative_code == fund_code,
            )
        )
        .order_by(
            (FundShare.share_code == fund_code).desc(),
            (FundShare.share_code == FundContract.representative_code).desc(),
            FundShare.share_code,
        )
    ).all()
    targets = _targets_from_rows(rows)
    if not targets:
        raise AnalysisScopeError(
            f"Fund {fund_code} is not a direct active fund with parsed 2026 Q2 holdings"
        )
    return targets[0]


def resolve_analysis_scope(
    session: Session,
    *,
    portfolio: bool = False,
    fund_codes: tuple[str, ...] = (),
) -> list[AnalysisTarget]:
    """Require portfolio or explicit codes so callers cannot accidentally scan all funds."""

    if portfolio and fund_codes:
        raise AnalysisScopeError("Choose portfolio scope or explicit fund codes, not both")
    if portfolio:
        return select_portfolio_active_funds(session)
    if not fund_codes:
        raise AnalysisScopeError("Analysis requires portfolio scope or an explicit fund code")
    seen: set[int] = set()
    targets: list[AnalysisTarget] = []
    for code in fund_codes:
        target = select_explicit_active_fund(session, code)
        if target.share_id not in seen:
            targets.append(target)
            seen.add(target.share_id)
    return targets


def _eligible_target_query() -> Select[tuple[FundContract, FundShare, FundReport]]:
    direct_holding_exists = (
        select(ReportSecurityHolding.id)
        .where(
            ReportSecurityHolding.fund_report_id == FundReport.id,
            ReportSecurityHolding.exposure_basis == "DIRECT",
            ReportSecurityHolding.security_type == "EQUITY",
            ReportSecurityHolding.nav_pct > 0,
        )
        .exists()
    )
    wrapper = func.upper(func.coalesce(FundContract.wrapper_type, ""))
    return (
        select(FundContract, FundShare, FundReport)
        .join(FundShare, FundShare.fund_contract_id == FundContract.id)
        .join(FundReport, FundReport.fund_contract_id == FundContract.id)
        .where(
            FundReport.report_type == "QUARTERLY",
            FundReport.report_year == 2026,
            FundReport.report_quarter == 2,
            FundReport.period_end == Q2_PERIOD_END,
            func.lower(FundReport.parse_status) == "parsed",
            FundReport.public_available_at.is_not(None),
            FundContract.is_user_selected.is_(True),
            wrapper == ACTIVE_WRAPPER,
            direct_holding_exists,
        )
    )


def _targets_from_rows(
    rows: Iterable[Any],
) -> list[AnalysisTarget]:
    result: list[AnalysisTarget] = []
    seen: set[int] = set()
    for fund, share, report in rows:
        if share.id in seen:
            continue
        seen.add(share.id)
        result.append(
            AnalysisTarget(
                fund_id=fund.id,
                fund_name=fund.canonical_name,
                representative_code=fund.representative_code,
                strategy_type=fund.strategy_type,
                wrapper_type=fund.wrapper_type,
                tech_scope=fund.tech_scope,
                share_id=share.id,
                share_code=share.share_code,
                share_currency=share.currency,
                report_id=report.id,
            )
        )
    return result


def _validate_fund_code(value: str) -> None:
    if len(value) != 6 or not value.isdigit():
        raise AnalysisScopeError("fund code must contain exactly six digits")
