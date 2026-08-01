from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    DailyFundNav,
    FundContract,
    FundShare,
    PortfolioCashFlow,
    PortfolioPosition,
)
from backend.app.portfolio import import_portfolio


def test_import_portfolio_anchors_nav_and_preserves_dividend_aware_platform_values(
    db_session: Session, tmp_path
) -> None:
    fund = FundContract(
        canonical_name="测试全球基金",
        manager_name="测试基金",
        representative_code="123456",
    )
    db_session.add(fund)
    db_session.flush()
    share = FundShare(
        fund_contract_id=fund.id,
        share_code="123456",
        currency="CNY",
    )
    db_session.add(share)
    db_session.flush()
    db_session.add(
        DailyFundNav(
            fund_share_id=share.id,
            nav_date=date(2026, 7, 30),
            unit_nav=Decimal("1.254"),
            source_provider="EASTMONEY",
            raw_payload_hash="a" * 64,
        )
    )
    db_session.commit()
    path = tmp_path / "portfolio.json"
    path.write_text(
        json.dumps(
            {
                "positions": [
                    {
                        "share_code": "123456",
                        "platform": "测试平台",
                        "snapshot_date": "2026-08-01",
                        "market_value": "10000.00",
                        "holding_profit": "500.00",
                        "holding_return_pct": "5.00",
                        "cumulative_profit": "750.00",
                        "recurring_plan": {
                            "gross_amount": "100",
                            "fee_pct": "0.15",
                        },
                        "cash_flows": [
                            {"occurred_on": "2024-01-18", "amount": "100.00"},
                            {"occurred_year": 2025, "amount": "200.00"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = import_portfolio(db_session, path)

    assert result.positions_written == 1
    assert result.cash_flows_written == 2
    position = db_session.scalar(select(PortfolioPosition))
    assert position is not None
    assert position.anchor_nav_date == date(2026, 7, 30)
    assert position.anchor_unit_nav == Decimal("1.25400000")
    assert position.reported_return_pct == Decimal("5.00000000")
    assert position.reported_cumulative_profit_amount == Decimal("750.000000")
    assert position.recurring_net_amount == Decimal("99.850000")
    assert position.manual_purchase_fee_pct == Decimal("0.15000000")
    assert "现金分红" in (position.data_quality_note or "")
    flows = list(db_session.scalars(select(PortfolioCashFlow).order_by(PortfolioCashFlow.id)))
    assert [(flow.occurred_on, flow.occurred_year, flow.amount) for flow in flows] == [
        (date(2024, 1, 18), 2024, Decimal("100.000000")),
        (None, 2025, Decimal("200.000000")),
    ]
