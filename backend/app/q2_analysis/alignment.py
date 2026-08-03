"""Transparent market-session alignment without per-fund lag fitting."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Final, Literal, cast

from backend.app.q2_analysis.market_provider import MarketPoint, MarketSeries

AlignmentPolicy = Literal[
    "US_PREVIOUS_COMPLETED_SESSION",
    "ASIA_SAME_OR_PREVIOUS_SESSION",
    "QDII_SAME_VALUATION_SESSION",
    "MIXED_BY_SECURITY_MARKET",
]
ALLOWED_POLICIES: Final = {
    "US_PREVIOUS_COMPLETED_SESSION",
    "ASIA_SAME_OR_PREVIOUS_SESSION",
    "QDII_SAME_VALUATION_SESSION",
    "MIXED_BY_SECURITY_MARKET",
}


@dataclass(frozen=True, slots=True)
class AlignedMarketReturn:
    nav_date: date
    trade_date: date | None
    previous_trade_date: date | None
    local_return_pct: Decimal | None
    fx_return_pct: Decimal | None
    share_currency_return_pct: Decimal | None
    alignment_policy: str
    carried_forward: bool


def policy_for_market(market: str | None) -> AlignmentPolicy:
    if market in {"US", "UK"}:
        return "US_PREVIOUS_COMPLETED_SESSION"
    return "ASIA_SAME_OR_PREVIOUS_SESSION"


def align_returns(
    nav_dates: list[date],
    price_series: MarketSeries,
    *,
    security_market: str | None,
    security_currency: str,
    share_currency: str,
    fx_series: MarketSeries | None,
    policy: AlignmentPolicy = "MIXED_BY_SECURITY_MARKET",
) -> list[AlignedMarketReturn]:
    """Align adjusted prices and exact FX-converted returns to NAV dates."""

    if policy not in ALLOWED_POLICIES:
        raise ValueError(f"Unsupported alignment policy: {policy}")
    effective_policy = (
        policy_for_market(security_market)
        if policy == "MIXED_BY_SECURITY_MARKET"
        else policy
    )
    dates = sorted(dict.fromkeys(nav_dates))
    price_points = sorted(price_series.points, key=lambda item: item.trade_date)
    price_dates = [item.trade_date for item in price_points]
    fx_points = sorted(fx_series.points, key=lambda item: item.trade_date) if fx_series else []
    fx_dates = [item.trade_date for item in fx_points]
    same_currency = security_currency.upper() == share_currency.upper()
    if not same_currency and fx_series is None:
        fx_points = []
        fx_dates = []

    result: list[AlignedMarketReturn] = []
    last_selected: MarketPoint | None = None
    for nav_date in dates:
        cutoff = (
            nav_date - timedelta(days=1)
            if effective_policy == "US_PREVIOUS_COMPLETED_SESSION"
            else nav_date
        )
        current = _latest_on_or_before(price_points, price_dates, cutoff)
        if current is None:
            result.append(
                AlignedMarketReturn(
                    nav_date=nav_date,
                    trade_date=None,
                    previous_trade_date=None,
                    local_return_pct=None,
                    fx_return_pct=None,
                    share_currency_return_pct=None,
                    alignment_policy=effective_policy,
                    carried_forward=False,
                )
            )
            continue

        carried_forward = (
            last_selected is not None and current.trade_date == last_selected.trade_date
        )
        previous = last_selected
        if previous is None:
            previous = _previous_before(price_points, price_dates, current.trade_date)
        local_return = None
        if previous is not None and not carried_forward:
            local_return = _return_pct(previous.adjusted_close, current.adjusted_close)
        fx_return: Decimal | None
        converted_return: Decimal | None
        if previous is None or carried_forward:
            fx_return = None
            converted_return = None
        elif same_currency:
            fx_return = None
            converted_return = local_return
        else:
            previous_fx = _latest_on_or_before(fx_points, fx_dates, previous.trade_date)
            current_fx = _latest_on_or_before(fx_points, fx_dates, current.trade_date)
            if (
                previous_fx is None
                or current_fx is None
                or previous_fx.trade_date != previous.trade_date
                or current_fx.trade_date != current.trade_date
            ):
                fx_return = None
                converted_return = None
            else:
                fx_return = _return_pct(previous_fx.adjusted_close, current_fx.adjusted_close)
                converted_return = _return_pct(
                    previous.adjusted_close * previous_fx.adjusted_close,
                    current.adjusted_close * current_fx.adjusted_close,
                )
        result.append(
            AlignedMarketReturn(
                nav_date=nav_date,
                trade_date=current.trade_date,
                previous_trade_date=previous.trade_date if previous else None,
                local_return_pct=local_return,
                fx_return_pct=fx_return,
                share_currency_return_pct=converted_return,
                alignment_policy=effective_policy,
                carried_forward=carried_forward,
            )
        )
        last_selected = current
    return result


def normalize_policy(value: str) -> AlignmentPolicy:
    normalized = value.strip().upper()
    if normalized not in ALLOWED_POLICIES:
        raise ValueError(f"Unsupported alignment policy: {value}")
    return cast(AlignmentPolicy, normalized)


def _latest_on_or_before(
    points: list[MarketPoint], point_dates: list[date], cutoff: date
) -> MarketPoint | None:
    index = bisect_right(point_dates, cutoff) - 1
    return points[index] if index >= 0 else None


def _previous_before(
    points: list[MarketPoint], point_dates: list[date], current_date: date
) -> MarketPoint | None:
    index = bisect_right(point_dates, current_date - timedelta(days=1)) - 1
    return points[index] if index >= 0 else None


def _return_pct(previous: Decimal, current: Decimal) -> Decimal:
    return (current / previous - Decimal("1")) * Decimal("100")
