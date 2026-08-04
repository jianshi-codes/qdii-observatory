from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ingestion.fee_pipeline import sync_portfolio_fees
from backend.app.ingestion.providers.base import FundFeeObservation, ProviderSchemaError
from backend.app.ingestion.providers.fees import parse_eastmoney_fee_page
from backend.app.models import DailyFundFee, FundContract, FundShare, PortfolioPosition


def _fee_html(code: str) -> bytes:
    return f"""
    <html><body><h1>测试基金({code})</h1>
    <p>购买手续费：<b class="sourcerate">1.50%</b>&nbsp;<b>0.15%</b></p>
    <table><tr><td>管理费率</td><td>1.20%（每年）</td>
    <td>托管费率</td><td>0.20%（每年）</td>
    <td>销售服务费率</td><td>---</td></tr></table>
    </body></html>
    """.encode()


def test_parse_eastmoney_fee_page_keeps_operating_and_reference_purchase_fees() -> None:
    observation = parse_eastmoney_fee_page(
        _fee_html("006555"),
        "006555",
        source_url="https://example.test/fee",
    )

    assert observation.management_fee_pct_annual == Decimal("1.20")
    assert observation.custody_fee_pct_annual == Decimal("0.20")
    assert observation.sales_service_fee_pct_annual is None
    assert observation.standard_purchase_fee_pct == Decimal("1.50")
    assert observation.discounted_purchase_fee_pct == Decimal("0.15")


def test_parse_eastmoney_fee_page_allows_missing_optional_sales_service_fee() -> None:
    payload = _fee_html("002892").replace("<td>销售服务费率</td><td>---</td>".encode(), b"")

    observation = parse_eastmoney_fee_page(
        payload,
        "002892",
        source_url="https://example.test/fee",
    )

    assert observation.management_fee_pct_annual == Decimal("1.20")
    assert observation.custody_fee_pct_annual == Decimal("0.20")
    assert observation.sales_service_fee_pct_annual is None


def test_parse_eastmoney_fee_page_fails_closed_when_operating_fees_are_missing() -> None:
    with pytest.raises(ProviderSchemaError, match="管理费率"):
        parse_eastmoney_fee_page(
            b"<html><body>test (006555)</body></html>",
            "006555",
            source_url="https://example.test/fee",
        )


def test_sync_portfolio_fees_archives_and_writes_daily_snapshot(
    db_session: Session, tmp_path
) -> None:
    fund = FundContract(
        canonical_name="测试基金",
        manager_name="测试管理人",
        representative_code="006555",
    )
    db_session.add(fund)
    db_session.flush()
    share = FundShare(fund_contract_id=fund.id, share_code="006555", currency="CNY")
    db_session.add(share)
    db_session.flush()
    db_session.add(
        PortfolioPosition(
            fund_share_id=share.id,
            platform="测试平台",
            snapshot_date=date(2026, 8, 1),
            currency="CNY",
            reported_units=Decimal("10000"),
            reported_market_value=Decimal("10000"),
            reported_profit_amount=Decimal("1000"),
            reported_return_pct=Decimal("10"),
            anchor_nav_date=date(2026, 7, 30),
            anchor_unit_nav=Decimal("1"),
        )
    )
    db_session.commit()

    class FakeProvider:
        name = "FEE_FIXTURE"
        version = "v1"

        def fetch(self, share_code: str) -> FundFeeObservation:
            return FundFeeObservation(
                provider_name=self.name,
                provider_version=self.version,
                share_code=share_code,
                observed_at=datetime(2026, 8, 1, tzinfo=UTC),
                management_fee_pct_annual=Decimal("1.20"),
                custody_fee_pct_annual=Decimal("0.20"),
                sales_service_fee_pct_annual=Decimal("0"),
                standard_purchase_fee_pct=Decimal("1.50"),
                discounted_purchase_fee_pct=Decimal("0.15"),
                raw_payload=_fee_html(share_code),
                source_url="https://example.test/fee",
                mime_type="text/html",
                confidence=Decimal("0.95"),
            )

    run = sync_portfolio_fees(db_session, FakeProvider(), tmp_path)

    assert run.status == "succeeded"
    fee = db_session.scalar(select(DailyFundFee))
    assert fee is not None
    assert fee.snapshot_date == date(2026, 8, 1)
    assert fee.management_fee_pct_annual == Decimal("1.20000000")
    assert (tmp_path / "fees" / "fee_fixture" / "006555").is_dir()
