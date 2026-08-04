"""Create daily recurring orders and settle them when their valuation NAV arrives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    DailyFundNav,
    FundContract,
    FundShare,
    PortfolioPosition,
    PortfolioRecurringExecution,
    PortfolioRecurringOrder,
)

QUANTITY_SCALE = Decimal("0.00000001")
SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class RecurringOrderCreationResult:
    orders_created: int
    positions_ordered: int
    order_date: date


@dataclass(frozen=True, slots=True)
class RecurringSettlementResult:
    orders_settled: int
    executions_written: int
    positions_updated: int
    latest_nav_date: date | None


def _local_today() -> date:
    return datetime.now(SHANGHAI).date()


def _add_weekdays(value: date, days: int) -> date:
    result = value
    remaining = days
    while remaining > 0:
        result += timedelta(days=1)
        if result.weekday() < 5:
            remaining -= 1
    return result


def _plan_positions(
    session: Session,
    *,
    fund_codes: tuple[str, ...],
) -> list[PortfolioPosition]:
    return list(
        session.scalars(
            select(PortfolioPosition)
            .join(FundShare, PortfolioPosition.fund_share_id == FundShare.id)
            .join(FundContract, FundShare.fund_contract_id == FundContract.id)
            .where(
                PortfolioPosition.is_active.is_(True),
                PortfolioPosition.recurring_frequency == "DAILY",
                PortfolioPosition.recurring_gross_amount.is_not(None),
                PortfolioPosition.recurring_fee_pct.is_not(None),
                PortfolioPosition.recurring_net_amount.is_not(None),
                FundContract.representative_code.in_(fund_codes),
            )
            .order_by(PortfolioPosition.id)
        ).all()
    )


def create_recurring_orders(
    session: Session,
    *,
    fund_codes: tuple[str, ...],
    order_date: date | None = None,
) -> RecurringOrderCreationResult:
    """Create one immutable plan snapshot per position for the local business date."""

    current_date = order_date or _local_today()
    if current_date.weekday() >= 5:
        return RecurringOrderCreationResult(0, 0, current_date)
    positions = _plan_positions(session, fund_codes=fund_codes)
    if not positions:
        return RecurringOrderCreationResult(0, 0, current_date)
    existing_position_ids = set(
        session.scalars(
            select(PortfolioRecurringOrder.portfolio_position_id).where(
                PortfolioRecurringOrder.portfolio_position_id.in_(
                    [position.id for position in positions]
                ),
                PortfolioRecurringOrder.order_date == current_date,
            )
        ).all()
    )
    created = 0
    for position in positions:
        if position.id in existing_position_ids:
            continue
        gross_amount = position.recurring_gross_amount
        fee_pct = position.recurring_fee_pct
        net_amount = position.recurring_net_amount
        if gross_amount is None or fee_pct is None or net_amount is None:
            continue
        session.add(
            PortfolioRecurringOrder(
                portfolio_position_id=position.id,
                order_date=current_date,
                expected_confirmation_date=_add_weekdays(
                    current_date,
                    position.recurring_confirmation_lag_days,
                ),
                status="PENDING",
                gross_amount=gross_amount,
                fee_pct=fee_pct,
                net_amount=net_amount,
            )
        )
        created += 1
    session.commit()
    return RecurringOrderCreationResult(created, created, current_date)


def recurring_plans_pending(
    session: Session,
    *,
    fund_codes: tuple[str, ...],
    order_date: date | None = None,
) -> bool:
    """Return whether today's order is missing or an existing order can now settle."""

    current_date = order_date or _local_today()
    positions = _plan_positions(session, fund_codes=fund_codes)
    if current_date.weekday() < 5:
        existing_position_ids = set(
            session.scalars(
                select(PortfolioRecurringOrder.portfolio_position_id).where(
                    PortfolioRecurringOrder.portfolio_position_id.in_(
                        [position.id for position in positions]
                    ),
                    PortfolioRecurringOrder.order_date == current_date,
                )
            ).all()
        )
        if any(position.id not in existing_position_ids for position in positions):
            return True
    settleable = session.scalar(
        select(PortfolioRecurringOrder.id)
        .join(
            PortfolioPosition,
            PortfolioRecurringOrder.portfolio_position_id == PortfolioPosition.id,
        )
        .join(FundShare, PortfolioPosition.fund_share_id == FundShare.id)
        .join(FundContract, FundShare.fund_contract_id == FundContract.id)
        .join(
            DailyFundNav,
            (DailyFundNav.fund_share_id == PortfolioPosition.fund_share_id)
            & (DailyFundNav.nav_date == PortfolioRecurringOrder.order_date),
        )
        .where(
            PortfolioRecurringOrder.status == "PENDING",
            FundContract.representative_code.in_(fund_codes),
        )
        .limit(1)
    )
    return settleable is not None


def settle_recurring_plans(
    session: Session,
    *,
    fund_codes: tuple[str, ...],
) -> RecurringSettlementResult:
    """Settle pending orders only when the exact order-date NAV is source-backed."""

    orders = list(
        session.scalars(
            select(PortfolioRecurringOrder)
            .join(
                PortfolioPosition,
                PortfolioRecurringOrder.portfolio_position_id == PortfolioPosition.id,
            )
            .join(FundShare, PortfolioPosition.fund_share_id == FundShare.id)
            .join(FundContract, FundShare.fund_contract_id == FundContract.id)
            .where(
                PortfolioRecurringOrder.status == "PENDING",
                PortfolioPosition.is_active.is_(True),
                FundContract.representative_code.in_(fund_codes),
            )
            .order_by(PortfolioRecurringOrder.order_date, PortfolioRecurringOrder.id)
        ).all()
    )
    settled_orders = 0
    written = 0
    updated_position_ids: set[int] = set()
    latest_settled: date | None = None
    for order in orders:
        position = order.portfolio_position
        nav = session.scalar(
            select(DailyFundNav)
            .where(
                DailyFundNav.fund_share_id == position.fund_share_id,
                DailyFundNav.nav_date == order.order_date,
            )
            .order_by(DailyFundNav.id.desc())
            .limit(1)
        )
        if nav is None:
            continue
        execution = session.scalar(
            select(PortfolioRecurringExecution).where(
                PortfolioRecurringExecution.portfolio_position_id == position.id,
                PortfolioRecurringExecution.nav_date == order.order_date,
            )
        )
        if execution is None:
            units = (order.net_amount / nav.unit_nav).quantize(
                QUANTITY_SCALE, rounding=ROUND_HALF_UP
            )
            execution = PortfolioRecurringExecution(
                portfolio_position_id=position.id,
                nav_date=nav.nav_date,
                unit_nav=nav.unit_nav,
                gross_amount=order.gross_amount,
                fee_pct=order.fee_pct,
                net_amount=order.net_amount,
                units=units,
                source_provider=nav.source_provider,
            )
            session.add(execution)
            session.flush()
            written += 1
        order.status = "SETTLED"
        order.settled_execution_id = execution.id
        order.confirmed_at = datetime.now(UTC)
        settled_orders += 1
        updated_position_ids.add(position.id)
        latest_settled = (
            nav.nav_date
            if latest_settled is None or nav.nav_date > latest_settled
            else latest_settled
        )
    session.commit()
    return RecurringSettlementResult(
        orders_settled=settled_orders,
        executions_written=written,
        positions_updated=len(updated_position_ids),
        latest_nav_date=latest_settled,
    )
