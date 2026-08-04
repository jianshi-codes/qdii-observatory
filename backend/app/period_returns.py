"""Pure period-return calculations over official fund NAV observations."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

ReturnPeriod = Literal["DAILY", "MTD", "QTD"]


@dataclass(frozen=True)
class NavObservation:
    nav_date: date
    unit_nav: Decimal
    accumulated_nav: Decimal | None = None


@dataclass(frozen=True)
class PeriodReturn:
    return_pct: Decimal | None
    baseline_date: date | None
    end_date: date | None
    uses_accumulated_nav: bool
    status: Literal["READY", "MISSING_NAV", "MISSING_BASELINE"]


def period_boundary(as_of: date, period: ReturnPeriod) -> date | None:
    if period == "DAILY":
        return None
    if period == "MTD":
        return as_of.replace(day=1)
    quarter_month = ((as_of.month - 1) // 3) * 3 + 1
    return date(as_of.year, quarter_month, 1)


def calculate_period_return(
    observations: Sequence[NavObservation],
    *,
    period: ReturnPeriod,
    end_date: date,
    period_as_of: date | None = None,
) -> PeriodReturn:
    """Calculate a total return ending at the latest official NAV on/before end_date."""

    rows = sorted(
        (row for row in observations if row.nav_date <= end_date),
        key=lambda row: row.nav_date,
    )
    if not rows:
        return PeriodReturn(None, None, None, False, "MISSING_NAV")

    end = rows[-1]
    boundary = period_boundary(period_as_of or end_date, period)
    baseline = (
        rows[-2]
        if period == "DAILY" and len(rows) >= 2
        else next((row for row in reversed(rows) if boundary and row.nav_date < boundary), None)
    )
    if baseline is None:
        return PeriodReturn(None, None, end.nav_date, False, "MISSING_BASELINE")

    uses_accumulated = baseline.accumulated_nav is not None and end.accumulated_nav is not None
    baseline_value = (
        baseline.accumulated_nav
        if uses_accumulated and baseline.accumulated_nav is not None
        else baseline.unit_nav
    )
    end_value = (
        end.accumulated_nav
        if uses_accumulated and end.accumulated_nav is not None
        else end.unit_nav
    )
    return_pct = ((end_value / baseline_value) - Decimal("1")) * Decimal("100")
    return PeriodReturn(
        return_pct.quantize(Decimal("0.00000001")),
        baseline.nav_date,
        end.nav_date,
        uses_accumulated,
        "READY",
    )
