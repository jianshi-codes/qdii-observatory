"""Deterministic import of local, user-maintained portfolio snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ingestion.runs import record_issue, resolve_issues
from backend.app.models import DailyFundNav, FundShare, PortfolioCashFlow, PortfolioPosition

CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class PortfolioImportResult:
    positions_seen: int
    positions_written: int
    cash_flows_written: int


def import_portfolio(session: Session, path: Path) -> PortfolioImportResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return import_portfolio_payload(session, payload)


def import_portfolio_payload(
    session: Session,
    payload: object,
) -> PortfolioImportResult:
    if not isinstance(payload, dict) or not isinstance(payload.get("positions"), list):
        raise ValueError("Portfolio JSON must contain a positions array")
    positions = payload["positions"]
    written = cash_flows_written = 0
    seen_identities: set[tuple[str, str]] = set()
    for index, raw in enumerate(positions):
        if not isinstance(raw, dict):
            raise ValueError(f"positions[{index}] must be an object")
        share_code = _required_text(raw, "share_code")
        platform = _required_text(raw, "platform")
        identity = (platform, share_code)
        if identity in seen_identities:
            raise ValueError(f"Duplicate portfolio position: {platform}/{share_code}")
        seen_identities.add(identity)
        share = session.scalar(select(FundShare).where(FundShare.share_code == share_code))
        if share is None:
            raise ValueError(f"Portfolio share code is not in fund_share: {share_code}")
        snapshot_date = _date_value(raw.get("snapshot_date"), "snapshot_date")
        anchor = session.scalar(
            select(DailyFundNav)
            .where(
                DailyFundNav.fund_share_id == share.id,
                DailyFundNav.nav_date <= snapshot_date,
            )
            .order_by(DailyFundNav.nav_date.desc(), DailyFundNav.id.desc())
            .limit(1)
        )
        if anchor is None:
            raise ValueError(f"No NAV on or before {snapshot_date} for {share_code}")
        currency = str(raw.get("currency") or share.currency).strip().upper()
        if currency != share.currency:
            raise ValueError(
                f"Portfolio currency {currency} does not match "
                f"{share_code} currency {share.currency}"
            )
        market_value = _decimal(raw.get("market_value"), "market_value", positive=True)
        profit = _decimal(raw.get("holding_profit"), "holding_profit")
        return_pct = _decimal(raw.get("holding_return_pct"), "holding_return_pct")
        cumulative_profit = _optional_decimal(raw.get("cumulative_profit"), "cumulative_profit")
        recurring = raw.get("recurring_plan")
        if recurring is not None and not isinstance(recurring, dict):
            raise ValueError("recurring_plan must be an object")
        recurring_values = _recurring_values(recurring)
        purchase_fee = _optional_decimal(raw.get("purchase_fee_pct"), "purchase_fee_pct")
        if purchase_fee is None:
            purchase_fee = recurring_values[2]

        row = session.scalar(
            select(PortfolioPosition).where(
                PortfolioPosition.platform == platform,
                PortfolioPosition.fund_share_id == share.id,
            )
        )
        if row is None:
            row = PortfolioPosition(platform=platform, fund_share_id=share.id)
            session.add(row)
        row.snapshot_date = snapshot_date
        row.currency = currency
        row.reported_market_value = market_value
        row.reported_profit_amount = profit
        row.reported_return_pct = return_pct
        row.reported_cumulative_profit_amount = cumulative_profit
        row.anchor_nav_date = anchor.nav_date
        row.anchor_unit_nav = anchor.unit_nav
        row.recurring_frequency = recurring_values[0]
        row.recurring_gross_amount = recurring_values[1]
        row.recurring_fee_pct = recurring_values[2]
        row.recurring_net_amount = recurring_values[3]
        row.manual_purchase_fee_pct = purchase_fee
        row.manual_management_fee_pct_annual = _optional_decimal(
            raw.get("management_fee_pct_annual"), "management_fee_pct_annual"
        )
        row.manual_custody_fee_pct_annual = _optional_decimal(
            raw.get("custody_fee_pct_annual"), "custody_fee_pct_annual"
        )
        row.source_type = "USER_REPORTED"
        row.is_active = bool(raw.get("active", True))
        session.flush()

        cash_flows = raw.get("cash_flows")
        if cash_flows is not None:
            if not isinstance(cash_flows, list):
                raise ValueError("cash_flows must be an array")
            row.cash_flows.clear()
            for flow_index, flow in enumerate(cash_flows):
                if not isinstance(flow, dict):
                    raise ValueError(f"cash_flows[{flow_index}] must be an object")
                occurred_on = (
                    _date_value(flow["occurred_on"], "occurred_on")
                    if flow.get("occurred_on")
                    else None
                )
                occurred_year = int(
                    flow.get("occurred_year") or (occurred_on.year if occurred_on else 0)
                )
                if not 2000 <= occurred_year <= 2100:
                    raise ValueError("cash flow requires occurred_on or a valid occurred_year")
                flow_currency = str(flow.get("currency") or currency).strip().upper()
                if flow_currency != currency:
                    raise ValueError("cash flow currency must match the portfolio position")
                row.cash_flows.append(
                    PortfolioCashFlow(
                        flow_type="DIVIDEND",
                        occurred_on=occurred_on,
                        occurred_year=occurred_year,
                        amount=_decimal(flow.get("amount"), "cash flow amount", positive=True),
                        currency=flow_currency,
                        source_type="USER_REPORTED",
                        note=_optional_text(flow.get("note")),
                    )
                )
                cash_flows_written += 1

        has_cash_flows = bool(row.cash_flows)
        note = _quality_note(market_value, profit, return_pct, has_cash_flows)
        row.data_quality_note = note
        if note and not has_cash_flows:
            record_issue(
                session,
                fund_contract_id=share.fund_contract_id,
                fund_share_id=share.id,
                issue_code="PORTFOLIO_RETURN_MISMATCH",
                severity="WARNING",
                message=f"Portfolio return fields do not reconcile for {share_code}",
                details={
                    "platform": platform,
                    "reported_market_value": str(market_value),
                    "reported_profit_amount": str(profit),
                    "reported_return_pct": str(return_pct),
                    "note": note,
                },
            )
        else:
            resolve_issues(
                session,
                issue_codes=("PORTFOLIO_RETURN_MISMATCH",),
                fund_contract_id=share.fund_contract_id,
                fund_share_id=share.id,
            )
        written += 1
    session.commit()
    return PortfolioImportResult(
        positions_seen=len(positions),
        positions_written=written,
        cash_flows_written=cash_flows_written,
    )


def _recurring_values(
    recurring: dict[str, Any] | None,
) -> tuple[str | None, Decimal | None, Decimal | None, Decimal | None]:
    if recurring is None:
        return None, None, None, None
    frequency = str(recurring.get("frequency") or "DAILY").strip().upper()
    if frequency != "DAILY":
        raise ValueError("Only DAILY recurring plans are supported")
    gross = _decimal(recurring.get("gross_amount"), "recurring gross_amount", positive=True)
    fee = _decimal(recurring.get("fee_pct", 0), "recurring fee_pct")
    if fee < 0 or fee > 100:
        raise ValueError("recurring fee_pct must be between 0 and 100")
    expected_net = (gross / (Decimal("1") + fee / Decimal("100"))).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    net = _optional_decimal(recurring.get("net_amount"), "recurring net_amount")
    if net is None:
        net = expected_net
    if abs(net - expected_net) > CENT:
        raise ValueError(
            f"recurring net_amount {net} does not match gross/fee calculation {expected_net}"
        )
    return frequency, gross, fee, net


def _quality_note(
    market_value: Decimal,
    profit: Decimal,
    return_pct: Decimal,
    has_cash_flows: bool,
) -> str | None:
    if has_cash_flows:
        return (
            "平台口径包含现金分红等历史现金流；保留平台持有收益、收益率和累计收益，不互相反算覆盖。"
        )
    implied_cost = market_value - profit
    if implied_cost <= 0:
        return "按市值和持有收益无法得到正的持有成本；保留平台原值。"
    implied_return = profit / implied_cost * Decimal("100")
    if abs(implied_return - return_pct) > Decimal("1"):
        return (
            f"按市值与持有收益推算为 {implied_return.quantize(Decimal('0.01'))}% ，"
            f"与平台持有收益率 {return_pct}% 不一致；保留平台原值。"
        )
    return None


def _required_text(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _date_value(value: object, field: str) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be YYYY-MM-DD") from error


def _optional_decimal(value: object, field: str) -> Decimal | None:
    return None if value is None else _decimal(value, field)


def _decimal(value: object, field: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    if positive and result <= 0:
        raise ValueError(f"{field} must be positive")
    return result
