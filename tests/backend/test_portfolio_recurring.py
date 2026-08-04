from __future__ import annotations

from datetime import date
from decimal import Decimal

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
from backend.app.portfolio_recurring import create_recurring_orders, settle_recurring_plans


def _position_with_plan(session: Session) -> tuple[PortfolioPosition, FundShare]:
    fund = FundContract(
        canonical_name="测试定投基金",
        manager_name="测试基金",
        representative_code="123456",
        is_user_selected=True,
    )
    session.add(fund)
    session.flush()
    share = FundShare(
        fund_contract_id=fund.id,
        share_code="123456",
        currency="CNY",
    )
    session.add(share)
    session.flush()
    position = PortfolioPosition(
        fund_share_id=share.id,
        platform="测试平台",
        snapshot_date=date(2026, 7, 30),
        currency="CNY",
        reported_units=Decimal("1000"),
        reported_market_value=Decimal("1000"),
        reported_profit_amount=Decimal("100"),
        reported_return_pct=Decimal("10"),
        anchor_nav_date=date(2026, 7, 30),
        anchor_unit_nav=Decimal("1"),
        recurring_frequency="DAILY",
        recurring_gross_amount=Decimal("100"),
        recurring_fee_pct=Decimal("1"),
        recurring_net_amount=Decimal("99"),
    )
    session.add(position)
    session.commit()
    return position, share


def _nav(session: Session, share: FundShare, nav_date: date, unit_nav: str) -> None:
    session.add(
        DailyFundNav(
            fund_share_id=share.id,
            nav_date=nav_date,
            unit_nav=Decimal(unit_nav),
            source_provider="FIXTURE",
            raw_payload_hash=f"{nav_date:%Y%m%d}".ljust(64, "0"),
        )
    )
    session.commit()


def test_recurring_order_waits_for_its_nav_and_settles_exactly_once(
    db_session: Session,
) -> None:
    position, share = _position_with_plan(db_session)

    created = create_recurring_orders(
        db_session,
        fund_codes=("123456",),
        order_date=date(2026, 8, 3),
    )
    repeated = create_recurring_orders(
        db_session,
        fund_codes=("123456",),
        order_date=date(2026, 8, 3),
    )

    assert created.orders_created == 1
    assert created.positions_ordered == 1
    assert repeated.orders_created == 0
    order = db_session.scalar(select(PortfolioRecurringOrder))
    assert order is not None
    assert order.status == "PENDING"
    assert order.order_date == date(2026, 8, 3)
    assert order.expected_confirmation_date == date(2026, 8, 5)
    assert order.gross_amount == Decimal("100")

    waiting = settle_recurring_plans(db_session, fund_codes=("123456",))
    assert waiting.orders_settled == 0
    assert waiting.executions_written == 0
    assert list(db_session.scalars(select(PortfolioRecurringExecution))) == []

    _nav(db_session, share, date(2026, 8, 3), "1.10")
    settled = settle_recurring_plans(db_session, fund_codes=("123456",))
    repeated_settlement = settle_recurring_plans(db_session, fund_codes=("123456",))

    assert settled.orders_settled == 1
    assert settled.executions_written == 1
    assert settled.positions_updated == 1
    assert settled.latest_nav_date == date(2026, 8, 3)
    assert repeated_settlement.orders_settled == 0
    db_session.refresh(order)
    assert order.status == "SETTLED"
    assert order.confirmed_at is not None
    assert order.settled_execution_id is not None
    executions = list(db_session.scalars(select(PortfolioRecurringExecution)))
    assert [(item.nav_date, item.units) for item in executions] == [
        (date(2026, 8, 3), Decimal("90.00000000")),
    ]


def test_recurring_settlement_does_not_invent_orders_for_new_nav_dates(
    db_session: Session,
) -> None:
    _, share = _position_with_plan(db_session)
    _nav(db_session, share, date(2026, 8, 3), "1.10")

    result = settle_recurring_plans(db_session, fund_codes=("123456",))

    assert result.executions_written == 0
    assert list(db_session.scalars(select(PortfolioRecurringExecution))) == []


def test_recurring_order_is_not_created_on_weekends(db_session: Session) -> None:
    _position_with_plan(db_session)

    result = create_recurring_orders(
        db_session,
        fund_codes=("123456",),
        order_date=date(2026, 8, 1),
    )

    assert result.orders_created == 0
    assert list(db_session.scalars(select(PortfolioRecurringOrder))) == []
