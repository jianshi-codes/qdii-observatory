from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app import api as api_module
from backend.app.models import (
    DailyExchangePrice,
    DailyExchangeRate,
    DailyFundFee,
    DailyFundNav,
    DailyPurchaseLimit,
    DataOperation,
    DataQualityIssue,
    ExposureFamily,
    FundContract,
    FundExposureFamily,
    FundRelation,
    FundReport,
    FundShare,
    IngestionRun,
    PortfolioCashFlow,
    PortfolioPosition,
    ReportCountryAllocation,
    ReportDerivedMetrics,
    ReportFundHolding,
    ReportIndustryAllocation,
    ReportSecurityHolding,
    SourceArtifact,
)


@pytest.fixture
def seeded(db_session: Session) -> dict[str, int]:
    feeder = FundContract(
        canonical_name="大成纳斯达克100ETF联接",
        manager_name="大成基金",
        representative_code="000834",
        original_category="美股纳斯达克/科技",
        wrapper_type="ETF_FEEDER",
        tech_scope="NASDAQ_100_MEGA_CAP_GROWTH",
    )
    target = FundContract(
        canonical_name="大成纳斯达克100ETF",
        manager_name="大成基金",
        representative_code="159513",
        original_category="美股纳斯达克/科技",
        wrapper_type="ETF",
        tech_scope="NASDAQ_100_MEGA_CAP_GROWTH",
    )
    db_session.add_all([feeder, target])
    db_session.flush()
    feeder_share = FundShare(
        fund_contract_id=feeder.id,
        share_code="000834",
        share_class="A",
        currency="CNY",
    )
    target_share = FundShare(
        fund_contract_id=target.id,
        share_code="159513",
        currency="CNY",
        is_exchange_traded=True,
        exchange="SZSE",
    )
    db_session.add_all([feeder_share, target_share])
    db_session.flush()
    reports = []
    for fund in (feeder, target):
        report = FundReport(
            fund_contract_id=fund.id,
            report_type="QUARTERLY",
            report_year=2026,
            report_quarter=2,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 6, 30),
            public_available_at=datetime(2026, 7, 20, tzinfo=UTC),
            source_provider="CSRC_EID",
            source_page_url="https://example.test/report",
            document_url="https://example.test/report.pdf",
            local_document_path=f"reports/{fund.representative_code}.pdf",
            mime_type="application/pdf",
            sha256=("a" if fund is feeder else "b") * 64,
            parser_version="fixture-v1",
            parse_status="PARSED",
            parse_confidence=Decimal("0.9900"),
        )
        db_session.add(report)
        db_session.flush()
        reports.append(report)
        db_session.add(
            ReportDerivedMetrics(
                fund_report_id=report.id,
                tech_scope="NASDAQ_100_MEGA_CAP_GROWTH",
                equity_nav_pct=Decimal("94.00000000"),
                fund_investment_nav_pct=(
                    Decimal("94.00000000") if fund is feeder else Decimal("0")
                ),
                cash_and_other_pct=Decimal("6.00000000"),
                us_country_pct=Decimal("90.00000000"),
                information_technology_pct=Decimal("50.00000000"),
                disclosed_top10_pct=Decimal("48.00000000"),
                lookthrough_coverage_pct=Decimal("94.00000000"),
                unresolved_fund_weight_pct=Decimal("0"),
                max_lookthrough_depth=1 if fund is feeder else 0,
                data_as_of=date(2026, 6, 30),
            )
        )
        for basis, country_weight, industry_weight in (
            (
                "DIRECT",
                Decimal("0") if fund is feeder else Decimal("90"),
                Decimal("0") if fund is feeder else Decimal("50"),
            ),
            ("LOOKTHROUGH", Decimal("90"), Decimal("50")),
        ):
            db_session.add_all(
                [
                    ReportCountryAllocation(
                        fund_report_id=report.id,
                        country_name_raw="美国",
                        country_name_normalized="US",
                        exposure_basis=basis,
                        nav_pct=country_weight,
                        rank=1,
                        source_section="国家分布",
                        raw_row={"country": "美国"},
                        parse_confidence=Decimal("0.9900"),
                    ),
                    ReportCountryAllocation(
                        fund_report_id=report.id,
                        country_name_raw="韩国",
                        country_name_normalized="KR",
                        exposure_basis=basis,
                        nav_pct=Decimal("3.00000000"),
                        rank=2,
                        source_section="国家分布",
                        raw_row={"country": "韩国"},
                        parse_confidence=Decimal("0.9900"),
                    ),
                    ReportCountryAllocation(
                        fund_report_id=report.id,
                        country_name_raw="日本",
                        country_name_normalized="日本",
                        exposure_basis=basis,
                        nav_pct=Decimal("2.00000000"),
                        rank=3,
                        source_section="国家分布",
                        raw_row={"country": "日本"},
                        parse_confidence=Decimal("0.9900"),
                    ),
                    ReportCountryAllocation(
                        fund_report_id=report.id,
                        country_name_raw="中国",
                        country_name_normalized="中国",
                        exposure_basis=basis,
                        nav_pct=Decimal("1.00000000"),
                        rank=4,
                        source_section="国家分布",
                        raw_row={"country": "中国"},
                        parse_confidence=Decimal("0.9900"),
                    ),
                    ReportCountryAllocation(
                        fund_report_id=report.id,
                        country_name_raw="中国香港",
                        country_name_normalized="HK",
                        exposure_basis=basis,
                        nav_pct=Decimal("4.00000000"),
                        rank=5,
                        source_section="国家分布",
                        raw_row={"country": "中国香港"},
                        parse_confidence=Decimal("0.9900"),
                    ),
                    ReportIndustryAllocation(
                        fund_report_id=report.id,
                        industry_name_raw="信息技术",
                        industry_name_normalized="INFORMATION_TECHNOLOGY",
                        exposure_basis=basis,
                        nav_pct=industry_weight,
                        rank=1,
                        source_section="行业分布",
                        raw_row={"industry": "信息技术"},
                        parse_confidence=Decimal("0.9900"),
                    ),
                    ReportSecurityHolding(
                        fund_report_id=report.id,
                        security_code_raw="NVDA",
                        security_name_raw="NVIDIA CORP",
                        security_name_normalized="NVIDIA",
                        security_name_zh="英伟达",
                        security_name_en="NVIDIA CORP",
                        exchange_raw="NASDAQ",
                        market_normalized="US",
                        country_normalized="US",
                        currency="USD",
                        quantity=Decimal("1000"),
                        security_type="COMMON_STOCK",
                        exposure_basis=basis,
                        fair_value_cny=Decimal("1000000.123456"),
                        nav_pct=Decimal("8.00000000"),
                        rank=1,
                        source_section="前十名股票",
                        raw_row={"ticker": "NVDA"},
                        parse_confidence=Decimal("0.9900"),
                    ),
                ]
            )

    db_session.add(
        ReportFundHolding(
            fund_report_id=reports[0].id,
            resolved_fund_contract_id=target.id,
            fund_code_raw="159513",
            fund_name_raw="大成纳斯达克100ETF",
            fund_name_normalized="大成纳斯达克100ETF",
            currency="CNY",
            is_unresolved=False,
            fair_value_cny=Decimal("94000000.000000"),
            nav_pct=Decimal("94.00000000"),
            rank=1,
            source_section="前十名基金投资明细",
            raw_row={"code": "159513"},
            parse_confidence=Decimal("0.9900"),
        )
    )
    db_session.add(
        FundRelation(
            source_fund_contract_id=feeder.id,
            target_fund_contract_id=target.id,
            relation_type="FEEDER_TO_TARGET_ETF",
            report_id=reports[0].id,
            weight_nav_pct=Decimal("94.00000000"),
            source_text="目标基金基本情况",
            confidence=Decimal("0.9900"),
        )
    )
    family = ExposureFamily(code="NASDAQ_100", display_name="纳斯达克100", description="经济暴露族")
    db_session.add(family)
    db_session.flush()
    db_session.add(
        FundExposureFamily(
            fund_contract_id=feeder.id,
            exposure_family_id=family.id,
            fund_report_id=reports[0].id,
            confidence=Decimal("0.9900"),
            source_text="业绩比较基准",
        )
    )

    for share, first, second in (
        (feeder_share, Decimal("1.00"), Decimal("1.01")),
        (target_share, Decimal("2.00"), Decimal("2.04")),
    ):
        db_session.add_all(
            [
                DailyFundNav(
                    fund_share_id=share.id,
                    nav_date=date(2026, 7, 29),
                    unit_nav=first,
                    calculated_daily_return_pct=Decimal("0.01000000"),
                    source_provider="EASTMONEY",
                    raw_payload_hash="c" * 64,
                ),
                DailyFundNav(
                    fund_share_id=share.id,
                    nav_date=date(2026, 7, 30),
                    unit_nav=second,
                    published_daily_return_pct=Decimal("0.75000000"),
                    calculated_daily_return_pct=Decimal("0.02000000"),
                    source_provider="EASTMONEY",
                    raw_payload_hash="d" * 64,
                ),
            ]
        )
    db_session.add(
        DailyExchangePrice(
            fund_share_id=target_share.id,
            trade_date=date(2026, 7, 30),
            open=Decimal("2.00"),
            high=Decimal("2.10"),
            low=Decimal("1.99"),
            close=Decimal("2.06"),
            pct_change=Decimal("0.03"),
            volume=Decimal("100000"),
            turnover=Decimal("205000.00"),
            premium_discount_pct=Decimal("0.00980392"),
            corresponding_nav_date=date(2026, 7, 30),
            source_provider="SZSE",
        )
    )
    manager_artifact = SourceArtifact(
        fund_contract_id=feeder.id,
        fund_share_id=feeder_share.id,
        artifact_type="PURCHASE_LIMIT_HTML",
        source_provider="FUND_MANAGER",
        source_url="https://example.test/direct-limit",
        local_path="purchase-limits/000834-direct.html",
        mime_type="text/html",
        sha256="e" * 64,
        byte_size=100,
        metadata_json={},
    )
    distributor_artifact = SourceArtifact(
        fund_contract_id=feeder.id,
        fund_share_id=feeder_share.id,
        artifact_type="PURCHASE_LIMIT_JSON",
        source_provider="DISTRIBUTOR",
        source_url="https://example.test/distribution-limit",
        local_path="purchase-limits/000834-distribution.json",
        mime_type="application/json",
        sha256="f" * 64,
        byte_size=100,
        metadata_json={},
    )
    target_artifact = SourceArtifact(
        fund_contract_id=target.id,
        fund_share_id=target_share.id,
        artifact_type="PURCHASE_LIMIT_JSON",
        source_provider="DISTRIBUTOR",
        source_url="https://example.test/159513-limit",
        local_path="purchase-limits/159513-distribution.json",
        mime_type="application/json",
        sha256="1" * 64,
        byte_size=100,
        metadata_json={},
    )
    db_session.add_all([manager_artifact, distributor_artifact, target_artifact])
    db_session.flush()
    db_session.add_all(
        [
            DailyPurchaseLimit(
                fund_share_id=feeder_share.id,
                snapshot_date=date(2026, 7, 30),
                channel_type="DIRECT",
                channel_key="FUND_MANAGER_DIRECT",
                channel_name="基金管理人直销",
                business_type="PURCHASE",
                availability_state="OPEN",
                cap_state="LIMITED",
                daily_limit_amount=Decimal("10000"),
                currency="CNY",
                limit_basis="PER_ACCOUNT_PER_DAY",
                share_scope="PER_SHARE",
                effective_from=date(2026, 7, 1),
                source_provider="FUND_MANAGER",
                source_url="https://example.test/direct-limit",
                source_artifact_id=manager_artifact.id,
                raw_payload_hash="e" * 64,
                raw_text="单日单账户申购上限为10000元",
                confidence=Decimal("0.9900"),
            ),
            DailyPurchaseLimit(
                fund_share_id=feeder_share.id,
                snapshot_date=date(2026, 7, 31),
                channel_type="DIRECT",
                channel_key="FUND_MANAGER_DIRECT",
                channel_name="基金管理人直销",
                business_type="PURCHASE",
                availability_state="OPEN",
                cap_state="LIMITED",
                daily_limit_amount=Decimal("5000"),
                currency="CNY",
                limit_basis="PER_ACCOUNT_PER_DAY",
                share_scope="ALL_SHARES_COMBINED",
                effective_from=date(2026, 7, 31),
                source_provider="FUND_MANAGER",
                source_url="https://example.test/direct-limit",
                source_artifact_id=manager_artifact.id,
                raw_payload_hash="e" * 64,
                raw_text="A/C类份额单日单账户合计申购上限为5000元",
                confidence=Decimal("0.9900"),
            ),
            DailyPurchaseLimit(
                fund_share_id=feeder_share.id,
                snapshot_date=date(2026, 7, 31),
                channel_type="DISTRIBUTION",
                channel_key="DISTRIBUTOR_FIXTURE",
                channel_name="示例代销渠道",
                business_type="PURCHASE",
                availability_state="PAUSED",
                cap_state="LIMITED",
                daily_limit_amount=Decimal("1000"),
                currency="CNY",
                limit_basis="PER_ACCOUNT_PER_DAY",
                share_scope="PER_SHARE",
                effective_from=date(2026, 7, 31),
                source_provider="DISTRIBUTOR",
                source_url="https://example.test/distribution-limit",
                source_artifact_id=distributor_artifact.id,
                raw_payload_hash="f" * 64,
                raw_text="渠道暂停申购；原单日限额1000元",
                confidence=Decimal("0.9000"),
            ),
            DailyPurchaseLimit(
                fund_share_id=target_share.id,
                snapshot_date=date(2026, 7, 30),
                channel_type="DISTRIBUTION",
                channel_key="DISTRIBUTOR_FIXTURE",
                channel_name="示例代销渠道",
                business_type="PURCHASE",
                availability_state="OPEN",
                cap_state="UNLIMITED",
                daily_limit_amount=None,
                currency="CNY",
                limit_basis="PER_ACCOUNT_PER_DAY",
                share_scope="PER_SHARE",
                source_provider="DISTRIBUTOR",
                source_url="https://example.test/159513-limit",
                source_artifact_id=target_artifact.id,
                raw_payload_hash="1" * 64,
                raw_text="申购开放且无上限",
                confidence=Decimal("0.9500"),
            ),
        ]
    )
    fee_artifact = SourceArtifact(
        fund_contract_id=feeder.id,
        fund_share_id=feeder_share.id,
        artifact_type="FUND_FEE_HTML",
        source_provider="EASTMONEY_FUND_FEE",
        source_url="https://example.test/fee",
        local_path="fees/000834.html",
        mime_type="text/html",
        sha256="2" * 64,
        byte_size=100,
        metadata_json={},
    )
    db_session.add(fee_artifact)
    db_session.flush()
    db_session.add(
        DailyFundFee(
            fund_share_id=feeder_share.id,
            snapshot_date=date(2026, 8, 1),
            management_fee_pct_annual=Decimal("1.20"),
            custody_fee_pct_annual=Decimal("0.20"),
            sales_service_fee_pct_annual=Decimal("0"),
            standard_purchase_fee_pct=Decimal("1.50"),
            discounted_purchase_fee_pct=Decimal("0.15"),
            source_provider="EASTMONEY_FUND_FEE",
            source_url="https://example.test/fee",
            source_artifact_id=fee_artifact.id,
            raw_payload_hash="2" * 64,
            confidence=Decimal("0.9500"),
        )
    )
    position = PortfolioPosition(
        fund_share_id=feeder_share.id,
        platform="测试平台",
        snapshot_date=date(2026, 7, 29),
        currency="CNY",
        reported_market_value=Decimal("10000"),
        reported_profit_amount=Decimal("1000"),
        reported_return_pct=Decimal("10"),
        reported_cumulative_profit_amount=Decimal("1200"),
        anchor_nav_date=date(2026, 7, 29),
        anchor_unit_nav=Decimal("1.00"),
        recurring_frequency="DAILY",
        recurring_gross_amount=Decimal("100"),
        recurring_fee_pct=Decimal("0.15"),
        recurring_net_amount=Decimal("99.85"),
        manual_purchase_fee_pct=Decimal("0.15"),
        source_type="USER_REPORTED",
    )
    db_session.add(position)
    db_session.flush()
    db_session.add(
        PortfolioCashFlow(
            portfolio_position_id=position.id,
            flow_type="DIVIDEND",
            occurred_year=2026,
            amount=Decimal("100"),
            currency="CNY",
            note="日期待补",
        )
    )
    run = IngestionRun(
        job_type="SYNC_REPORTS",
        status="PARTIAL",
        parameters={"year": 2026, "quarter": 2},
        records_seen=51,
        records_written=50,
        records_failed=1,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        DataQualityIssue(
            ingestion_run_id=run.id,
            fund_contract_id=feeder.id,
            fund_report_id=reports[0].id,
            issue_code="LOW_PARSE_CONFIDENCE",
            severity="WARNING",
            status="OPEN",
            message="Fixture issue",
            details={"threshold": "0.95"},
        )
    )
    db_session.commit()
    return {
        "feeder": feeder.id,
        "target": target.id,
        "feeder_report": reports[0].id,
        "feeder_share": feeder_share.id,
        "target_share": target_share.id,
    }


def test_all_fund_read_endpoints(client: TestClient, seeded: dict[str, int]) -> None:
    feeder_id = seeded["feeder"]
    responses = {
        "funds": client.get("/api/funds"),
        "fund": client.get(f"/api/funds/{feeder_id}"),
        "shares": client.get(f"/api/funds/{feeder_id}/shares"),
        "reports": client.get(f"/api/funds/{feeder_id}/reports"),
        "country": client.get(f"/api/funds/{feeder_id}/country-exposure?basis=LOOKTHROUGH"),
        "industry": client.get(f"/api/funds/{feeder_id}/industry-exposure?basis=LOOKTHROUGH"),
        "holdings": client.get(f"/api/funds/{feeder_id}/holdings?basis=LOOKTHROUGH"),
        "fund_holdings": client.get(f"/api/funds/{feeder_id}/fund-holdings"),
        "nav": client.get(f"/api/funds/{feeder_id}/nav"),
        "relations": client.get(f"/api/funds/{feeder_id}/relations"),
        "purchase_limits": client.get(f"/api/funds/{feeder_id}/purchase-limits"),
    }
    assert {name: response.status_code for name, response in responses.items()} == {
        name: 200 for name in responses
    }
    assert responses["funds"].json()["items"][0]["latest_report_status"] == "PARSED"
    summary = responses["funds"].json()["items"][0]
    assert summary["parse_confidence"] == "0.9900"
    assert summary["stock_holding_count"] == 1
    assert summary["fund_holding_count"] == 1
    assert summary["lookthrough_status"] == "resolved"
    assert summary["latest_nav_date"] == "2026-07-30"
    assert summary["latest_nav_return_pct"] == "0.75000000"
    assert summary["korea_country_pct"] == "3.00000000"
    assert summary["japan_country_pct"] == "2.00000000"
    assert summary["hong_kong_country_pct"] == "4.00000000"
    assert summary["china_country_pct"] == "1.00000000"
    assert summary["direct_purchase_limit"]["daily_limit_amount"] == "5000.000000"
    assert summary["distribution_purchase_limit"]["daily_limit_amount"] == "1000.000000"
    assert responses["fund"].json()["exposure_families"][0]["code"] == "NASDAQ_100"
    assert responses["shares"].json()[0]["share_code"] == "000834"
    assert responses["reports"].json()[0]["period_end"] == "2026-06-30"
    assert responses["country"].json()["items"][0]["name_normalized"] == "US"
    assert responses["industry"].json()["items"][0]["name_normalized"] == ("INFORMATION_TECHNOLOGY")
    assert responses["holdings"].json()["items"][0]["security_code_raw"] == "NVDA"
    assert (
        responses["fund_holdings"].json()["items"][0]["resolved_fund_contract_id"]
        == (seeded["target"])
    )
    assert len(responses["nav"].json()["items"]) == 2
    assert responses["nav"].json()["exchange_prices"] == []
    assert responses["relations"].json()[0]["target_fund_contract_id"] == seeded["target"]
    assert len(responses["purchase_limits"].json()["items"]) == 2


def test_provider_health_uses_latest_completed_real_request(
    client: TestClient, db_session: Session
) -> None:
    db_session.add_all(
        [
            IngestionRun(
                job_type="sync_nav",
                status="partial",
                parameters={"provider": "EASTMONEY_NAV"},
                started_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
                finished_at=datetime(2026, 8, 1, 2, tzinfo=UTC),
                records_failed=2,
            ),
            IngestionRun(
                job_type="sync_nav",
                status="succeeded",
                parameters={"provider": "EASTMONEY_NAV"},
                started_at=datetime(2026, 8, 2, 1, tzinfo=UTC),
                finished_at=datetime(2026, 8, 2, 2, tzinfo=UTC),
            ),
            IngestionRun(
                job_type="sync_reports",
                status="partial",
                parameters={"provider": "CSRC_EID"},
                started_at=datetime(2026, 8, 2, 3, tzinfo=UTC),
                finished_at=datetime(2026, 8, 2, 4, tzinfo=UTC),
                records_failed=3,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/provider-health")

    assert response.status_code == 200
    providers = {item["name"]: item for item in response.json()["providers"]}
    assert providers["eastmoney_nav"] == {
        "name": "eastmoney_nav",
        "enabled": True,
        "priority": 20,
        "status": "HEALTHY",
        "last_checked_at": "2026-08-02T02:00:00",
        "last_run_status": "succeeded",
        "records_failed": 0,
    }
    assert providers["csrc_reports"]["status"] == "DEGRADED"
    assert providers["csrc_reports"]["records_failed"] == 3
    assert providers["ecb_fx"]["status"] == "UNKNOWN"
    assert providers["ecb_fx"]["last_checked_at"] is None


def test_portfolio_uses_latest_nav_without_mixing_fee_deductions(
    client: TestClient, seeded: dict[str, int]
) -> None:
    response = client.get("/api/portfolio")

    assert response.status_code == 200
    payload = response.json()
    assert payload["latest_nav_date"] == "2026-07-30"
    position = payload["positions"][0]
    assert position["share_code"] == "000834"
    assert position["estimated_market_value"] == "10100.00"
    assert position["estimated_market_value_cny"] == "10100.00"
    assert position["estimated_profit_amount"] == "1100.00"
    assert position["estimated_profit_amount_cny"] == "1100.00"
    assert position["estimated_return_pct"] == "11.1000000000"
    assert position["estimated_daily_profit_amount"] == "100.00"
    assert position["estimated_daily_profit_amount_cny"] == "100.00"
    assert position["estimated_cumulative_profit_amount"] == "1300.00"
    assert position["cash_dividend_total"] == "100.00"
    assert position["recurring_plan"]["net_amount"] == "99.850000"
    assert position["fees"]["platform_purchase_fee_pct"] == "0.15000000"
    assert position["fees"]["management_fee_pct_annual"] == "1.20000000"
    assert payload["currency_summaries"][0]["estimated_market_value"] == "10100.00"
    assert payload["currency_summaries"][0]["estimated_return_pct"] == "11.10000000"
    assert payload["currency_summaries"][0]["estimated_daily_return_pct"] == "1.00000000"
    assert payload["currency_summaries"][0]["recurring_net_pct"] == "99.85000000"
    assert payload["converted_summary"]["estimated_market_value"] == "10100.00"
    assert payload["converted_summary"]["estimated_return_pct"] == "11.10000000"
    assert payload["converted_summary"]["estimated_daily_return_pct"] == "1.00000000"
    assert payload["converted_summary"]["usd_cny_rate"] is None


def test_portfolio_converts_usd_positions_with_latest_source_backed_rate(
    client: TestClient, db_session: Session, seeded: dict[str, int]
) -> None:
    fund = FundContract(
        canonical_name="测试美元基金",
        manager_name="测试基金",
        representative_code="123456",
    )
    db_session.add(fund)
    db_session.flush()
    share = FundShare(
        fund_contract_id=fund.id,
        share_code="123456",
        currency="USD",
    )
    db_session.add(share)
    db_session.flush()
    db_session.add_all(
        [
            DailyFundNav(
                fund_share_id=share.id,
                nav_date=date(2026, 7, 29),
                unit_nav=Decimal("1.00"),
                source_provider="FIXTURE",
                raw_payload_hash="4" * 64,
            ),
            DailyFundNav(
                fund_share_id=share.id,
                nav_date=date(2026, 7, 30),
                unit_nav=Decimal("1.10"),
                source_provider="FIXTURE",
                raw_payload_hash="5" * 64,
            ),
            PortfolioPosition(
                fund_share_id=share.id,
                platform="测试平台",
                snapshot_date=date(2026, 7, 29),
                currency="USD",
                reported_market_value=Decimal("100"),
                reported_profit_amount=Decimal("10"),
                reported_return_pct=Decimal("10"),
                anchor_nav_date=date(2026, 7, 29),
                anchor_unit_nav=Decimal("1.00"),
            ),
        ]
    )
    artifact = SourceArtifact(
        artifact_type="FX_RATE_XML",
        source_provider="ECB_REFERENCE_RATE",
        source_url="https://example.test/fx",
        local_path="fx/ecb.xml",
        mime_type="application/xml",
        sha256="3" * 64,
        byte_size=100,
        metadata_json={},
    )
    db_session.add(artifact)
    db_session.flush()
    db_session.add(
        DailyExchangeRate(
            base_currency="USD",
            quote_currency="CNY",
            rate_date=date(2026, 7, 31),
            rate=Decimal("7"),
            source_provider="ECB_REFERENCE_RATE",
            source_url="https://example.test/fx",
            source_artifact_id=artifact.id,
            raw_payload_hash="3" * 64,
            confidence=Decimal("0.99"),
        )
    )
    db_session.commit()

    payload = client.get("/api/portfolio").json()
    usd = next(row for row in payload["positions"] if row["currency"] == "USD")
    assert usd["estimated_market_value"] == "110.00"
    assert usd["estimated_market_value_cny"] == "770.00"
    assert usd["estimated_profit_amount_cny"] == "140.00"
    assert usd["estimated_daily_profit_amount_cny"] == "70.00"
    assert payload["converted_summary"] == {
        "currency": "CNY",
        "estimated_market_value": "10870.00",
        "estimated_profit_amount": "1240.00",
        "estimated_return_pct": "11.72402044",
        "estimated_daily_profit_amount": "170.00",
        "estimated_daily_return_pct": "1.58878505",
        "usd_cny_rate": "7.000000000000",
        "rate_date": "2026-07-31",
        "source_provider": "ECB_REFERENCE_RATE",
        "source_url": "https://example.test/fx",
    }


def test_purchase_limits_latest_snapshot_and_filters(
    client: TestClient, seeded: dict[str, int]
) -> None:
    response = client.get(f"/api/funds/{seeded['feeder']}/purchase-limits")
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    assert {row["snapshot_date"] for row in rows} == {"2026-07-31"}
    assert {row["source_provider"] for row in rows} == {"FUND_MANAGER", "DISTRIBUTOR"}
    paused = next(row for row in rows if row["availability_state"] == "PAUSED")
    assert paused["cap_state"] == "LIMITED"
    assert paused["daily_limit_amount"] == "1000.000000"

    filtered = client.get(
        f"/api/funds/{seeded['feeder']}/purchase-limits",
        params={"snapshot_date": "2026-07-30", "channel_type": "DIRECT"},
    )
    assert filtered.status_code == 200, filtered.text
    filtered_rows = filtered.json()["items"]
    assert len(filtered_rows) == 1
    assert filtered_rows[0]["daily_limit_amount"] == "10000.000000"

    missing_share = client.get(
        f"/api/funds/{seeded['feeder']}/purchase-limits",
        params={"share_code": "999999"},
    )
    assert missing_share.status_code == 404

    invalid_channel = client.get(
        f"/api/funds/{seeded['feeder']}/purchase-limits",
        params={"channel_type": "AGENCY"},
    )
    assert invalid_channel.status_code == 422


def test_purchase_limits_choose_latest_date_independently_per_share(
    client: TestClient, seeded: dict[str, int]
) -> None:
    feeder_response = client.get(f"/api/funds/{seeded['feeder']}/purchase-limits")
    target_response = client.get(f"/api/funds/{seeded['target']}/purchase-limits")
    assert {row["snapshot_date"] for row in feeder_response.json()["items"]} == {"2026-07-31"}
    assert {row["snapshot_date"] for row in target_response.json()["items"]} == {"2026-07-30"}


def test_purchase_limit_coverage_uses_global_latest_snapshot_date(
    client: TestClient, seeded: dict[str, int]
) -> None:
    response = client.get("/api/purchase-limit-coverage")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "total_funds": 2,
        "covered_funds": 1,
        "total_shares": 2,
        "covered_shares": 1,
        "latest_snapshot_date": "2026-07-31",
        "availability_state_counts": {"OPEN": 1, "PAUSED": 1},
        "cap_state_counts": {"LIMITED": 2},
    }


def test_compare_and_operations_endpoints(client: TestClient, seeded: dict[str, int]) -> None:
    response = client.get(
        "/api/compare",
        params=[
            ("fund_ids", seeded["feeder"]),
            ("fund_ids", seeded["target"]),
        ],
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["exposure_basis"] == "LOOKTHROUGH"
    assert len(payload["funds"]) == 2
    assert payload["holding_overlaps"][0]["items"][0]["security_code"] == "NVDA"
    assert payload["return_correlations"][0]["common_observations"] == 2
    assert payload["return_correlations"][0]["correlation"] == "1.0"

    runs = client.get("/api/ingestion-runs?status=PARTIAL")
    issues = client.get("/api/data-quality-issues?status=OPEN&severity=WARNING")
    assert runs.status_code == 200
    assert runs.json()[0]["records_seen"] == 51
    assert issues.status_code == 200
    assert issues.json()[0]["issue_code"] == "LOW_PARSE_CONFIDENCE"
    assert issues.json()[0]["representative_code"] == "000834"
    assert issues.json()[0]["fund_name"] == "大成纳斯达克100ETF联接"
    assert "https://example.test/report" in issues.json()[0]["source_urls"]
    assert "https://example.test/direct-limit" not in issues.json()[0]["source_urls"]
    assert "https://example.test/159513-limit" not in issues.json()[0]["source_urls"]


def test_quality_issue_sources_are_limited_to_the_exact_share_and_contract(
    client: TestClient,
    db_session: Session,
    seeded: dict[str, int],
) -> None:
    db_session.add_all(
        [
            SourceArtifact(
                fund_contract_id=seeded["feeder"],
                fund_share_id=seeded["feeder_share"],
                artifact_type="NAV_JSON",
                source_provider="NAV_FIXTURE",
                source_url="https://example.test/unrelated-nav",
                local_path="nav/000834.json",
                mime_type="application/json",
                sha256="9" * 64,
                byte_size=100,
                metadata_json={},
            ),
            DataQualityIssue(
                fund_contract_id=seeded["feeder"],
                fund_share_id=seeded["feeder_share"],
                issue_code="SALES_LIMIT_COVERAGE_INCOMPLETE",
                severity="WARNING",
                status="OPEN",
                message="Fixture limit issue",
                details={"missing_channels": [], "unknown_states": []},
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/data-quality-issues?status=OPEN")

    assert response.status_code == 200
    issue = next(
        item for item in response.json() if item["issue_code"] == "SALES_LIMIT_COVERAGE_INCOMPLETE"
    )
    assert "https://example.test/direct-limit" in issue["source_urls"]
    assert "https://example.test/distribution-limit" in issue["source_urls"]
    assert "https://example.test/159513-limit" not in issue["source_urls"]
    assert "https://example.test/unrelated-nav" not in issue["source_urls"]


def test_data_preparation_status_reports_each_ready_stage(
    client: TestClient,
    seeded: dict[str, int],
) -> None:
    response = client.get("/api/operations/preparation-status")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload == {
        "active_operation": None,
        "latest_operation": None,
        "total_funds": 2,
        "total_shares": 2,
        "nav_ready_funds": 2,
        "latest_nav_date": "2026-07-30",
        "limit_ready_funds": 2,
        "latest_limit_snapshot_date": "2026-07-31",
        "report_year": 2026,
        "report_quarter": 2,
        "report_downloaded_funds": 2,
        "report_parsed_funds": 2,
        "lookthrough_ready_funds": 2,
    }


def test_prepare_operation_is_explicit_scoped_and_queued(
    client: TestClient,
    db_session: Session,
    seeded: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(api_module, "raw_data_dir", lambda: tmp_path)

    response = client.post(
        "/api/operations/prepare",
        json={"fund_codes": ["000834"], "lookback_days": 10},
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["operation"] == "prepare"
    assert payload["status"] == "queued"
    assert payload["fund_codes"] == ["000834"]
    assert payload["stage_total"] == 3
    queued = db_session.get(DataOperation, payload["id"])
    assert queued is not None
    assert queued.active_slot == 1


def test_archive_fund_preserves_data_and_updates_active_universe_counts(
    client: TestClient,
    db_session: Session,
    seeded: dict[str, int],
) -> None:
    response = client.post(f"/api/funds/{seeded['feeder']}/archive")

    assert response.status_code == 200
    assert response.json() == {
        "id": seeded["feeder"],
        "representative_code": "000834",
        "is_user_selected": False,
    }
    assert client.get("/api/funds").json()["total"] == 1
    assert client.get("/api/funds?is_user_selected=false").json()["total"] == 1
    preparation = client.get("/api/operations/preparation-status").json()
    assert preparation["total_funds"] == 1
    assert preparation["total_shares"] == 1
    coverage = client.get("/api/purchase-limit-coverage").json()
    assert coverage["total_funds"] == 1
    assert coverage["total_shares"] == 1
    archived = db_session.get(FundContract, seeded["feeder"])
    assert archived is not None
    assert archived.reports
    assert archived.shares


def test_today_estimate_is_not_applicable_to_exchange_traded_funds(
    client: TestClient,
    seeded: dict[str, int],
) -> None:
    response = client.get(f"/api/funds/{seeded['target']}/today-estimate?as_of=2026-08-03")

    assert response.status_code == 200
    payload = response.json()
    assert payload["prediction"] is None
    assert payload["consistency"]["status"] == "NOT_APPLICABLE"


def test_today_estimate_runs_only_for_one_explicit_direct_fund(
    client: TestClient,
    db_session: Session,
    seeded: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fund = db_session.get(FundContract, seeded["feeder"])
    assert fund is not None
    fund.wrapper_type = "DIRECT"
    report = fund.reports[0]
    db_session.add(
        ReportSecurityHolding(
            fund_report_id=report.id,
            security_code_raw="NVDA US",
            security_name_raw="NVIDIA CORP",
            security_name_normalized="NVIDIA",
            market_normalized="US",
            currency="USD",
            security_type="EQUITY",
            exposure_basis="DIRECT",
            nav_pct=Decimal("8"),
            rank=1,
            source_section="前十名股票",
            raw_row={"ticker": "NVDA"},
        )
    )
    db_session.commit()
    captured: dict[str, object] = {}

    class Result:
        def as_dict(self, *, include_series: bool) -> dict[str, object]:
            captured["include_series"] = include_series
            return {
                "fund_id": fund.id,
                "fund_code": "000834",
                "representative_code": "000834",
                "fund_name": fund.canonical_name,
                "share_code": "000834",
                "share_currency": "CNY",
                "data_as_of": date(2026, 7, 31),
                "market_data_fetched_at": datetime(2026, 8, 3, tzinfo=UTC),
                "report_period_end": date(2026, 6, 30),
                "report_public_available_at": datetime(2026, 7, 20, tzinfo=UTC),
                "analysis_start_date": date(2026, 7, 1),
                "as_of": date(2026, 8, 3),
                "analysis_mode": "Q2_LIVE",
                "model": "Q2_DISCLOSED_HOLDINGS_BASELINE",
                "prediction": {
                    "estimate_date": date(2026, 8, 3),
                    "nav_date": date(2026, 7, 31),
                    "actual_return_pct": None,
                    "actual_return_source": None,
                    "predicted_return_pct": Decimal("0.8"),
                    "lower_bound_pct": Decimal("0.2"),
                    "upper_bound_pct": Decimal("1.4"),
                    "known_contribution_pct": Decimal("0.8"),
                    "proxy_contribution_pct": None,
                    "fund_holding_contribution_pct": None,
                    "cash_contribution_pct": Decimal("0"),
                    "residual_pct": None,
                    "analysis_mode": "Q2_LIVE",
                    "confidence": "MEDIUM",
                    "coverage": {
                        "disclosed_security_weight_pct": Decimal("8"),
                        "mapped_security_weight_pct": Decimal("8"),
                        "priced_security_weight_pct": Decimal("8"),
                        "unresolved_security_weight_pct": Decimal("0"),
                        "missing_market_data_weight_pct": Decimal("0"),
                        "undisclosed_equity_weight_pct": Decimal("86"),
                        "proxy_weight_pct": Decimal("0"),
                        "fund_holding_weight_pct": Decimal("0"),
                        "resolved_fund_holding_weight_pct": Decimal("0"),
                        "unresolved_fund_weight_pct": Decimal("0"),
                        "cash_weight_pct": Decimal("6"),
                        "total_explained_weight_pct": Decimal("14"),
                    },
                    "security_contributions": [],
                    "proxy_contributions": [],
                    "fund_holding_contributions": [],
                    "model": "Q2_DISCLOSED_HOLDINGS_BASELINE",
                },
                "latest_comparison": None,
                "consistency": {
                    "status": "INSUFFICIENT_DATA",
                    "observation_count": 1,
                    "mae_5_pct": None,
                    "mae_10_pct": None,
                    "mae_20_pct": None,
                    "signed_bias_5_pct": None,
                    "signed_bias_10_pct": None,
                    "cumulative_residual_pct": None,
                    "actual_predicted_correlation": None,
                    "same_direction_residual_streak": 0,
                    "recent_coverage_pct": Decimal("14"),
                    "explanation": "insufficient data",
                },
                "coverage": None,
                "prediction_observation_coverage_pct": Decimal("14"),
                "proxies": [],
                "unmapped_securities": [],
                "limitations": [],
                "sources": [],
                "market_data_errors": [],
                "series": [],
            }

    def fake_analyze(*args: object, **kwargs: object) -> Result:
        captured["target"] = args[1]
        captured["as_of"] = kwargs["as_of"]
        return Result()

    monkeypatch.setattr(api_module, "analyze_fund", fake_analyze)

    response = client.get(
        f"/api/funds/{fund.id}/today-estimate?share_code=000834&as_of=2026-08-03"
    )

    assert response.status_code == 200
    assert response.json()["prediction"]["predicted_return_pct"] == "0.8"
    assert captured["target"].fund_id == fund.id
    assert captured["as_of"] == date(2026, 8, 3)
    assert captured["include_series"] is False


def test_data_operation_rejects_unknown_fund_and_concurrent_run(
    client: TestClient,
    seeded: dict[str, int],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(api_module, "raw_data_dir", lambda: tmp_path)
    unknown = client.post(
        "/api/operations/sync-sales-limits",
        json={"fund_codes": ["999999"]},
    )
    assert unknown.status_code == 404

    queued = client.post(
        "/api/operations/sync-reports",
        json={"fund_codes": ["000834"]},
    )
    active = client.get("/api/operations/preparation-status")
    concurrent = client.post(
        "/api/operations/sync-sales-limits",
        json={"fund_codes": ["000834"]},
    )
    assert queued.status_code == 202
    assert active.status_code == 200
    assert active.json()["active_operation"] == "sync-reports"
    assert active.json()["latest_operation"]["status"] == "queued"
    assert concurrent.status_code == 409
    assert concurrent.json()["detail"] == "data operation 1 (sync-reports) is queued"
    archived = client.post(f"/api/funds/{seeded['target']}/archive")
    assert archived.status_code == 409
    assert "archive after it finishes" in archived.json()["detail"]


def test_filters_validation_and_not_found(client: TestClient, seeded: dict[str, int]) -> None:
    selected = client.get("/api/funds?manager_name=大成基金&is_user_selected=true")
    assert selected.status_code == 200
    assert selected.json()["total"] == 2

    assert client.get("/api/funds/999999").status_code == 404
    assert client.get(f"/api/funds/{seeded['feeder']}/nav?share_code=999999").status_code == 404
    duplicate_compare = client.get(
        "/api/compare",
        params=[
            ("fund_ids", seeded["feeder"]),
            ("fund_ids", seeded["feeder"]),
        ],
    )
    assert duplicate_compare.status_code == 422
