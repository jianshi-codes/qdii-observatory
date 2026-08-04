from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models import (
    DailyFundNav,
    DataOperation,
    FundContract,
    FundReport,
    FundShare,
    ReportCountryAllocation,
)


def add_fund(
    db: Session,
    *,
    code: str = "002891",
    name: str = "主动科技测试基金",
) -> tuple[FundContract, FundShare]:
    fund = FundContract(
        canonical_name=name,
        manager_name="测试基金",
        representative_code=code,
        strategy_type="主动混合",
        original_category="全球科技/互联网",
        tech_scope="GLOBAL_ACTIVE_TECH_HIGH",
    )
    db.add(fund)
    db.flush()
    share = FundShare(
        fund_contract_id=fund.id,
        share_code=code,
        share_class="A",
        currency="CNY",
    )
    db.add(share)
    db.flush()
    return fund, share


def add_nav(
    db: Session,
    share: FundShare,
    nav_date: date,
    unit_nav: str,
    accumulated_nav: str | None = None,
) -> None:
    db.add(
        DailyFundNav(
            fund_share_id=share.id,
            nav_date=nav_date,
            unit_nav=Decimal(unit_nav),
            accumulated_nav=Decimal(accumulated_nav) if accumulated_nav else None,
            source_provider="FIXTURE",
            raw_payload_hash=f"{share.id % 10}" * 64,
        )
    )


def test_active_tech_mtd_uses_prior_month_baseline_and_accumulated_nav(
    client: TestClient,
    db_session: Session,
) -> None:
    _, share = add_fund(db_session)
    add_nav(db_session, share, date(2026, 7, 31), "1.00", "1.00")
    add_nav(db_session, share, date(2026, 8, 1), "0.92", "1.02")
    db_session.commit()

    response = client.get(
        "/api/dashboards/active-tech/returns?pool=CORE&period=MTD&as_of=2026-08-01"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["common_comparable_date"] == "2026-08-01"
    assert payload["items"][0]["baseline_date"] == "2026-07-31"
    assert payload["items"][0]["return_pct"] == "2.00000000"
    assert payload["items"][0]["uses_accumulated_nav"] is True


def test_active_tech_mtd_uses_request_month_when_official_nav_lags(
    client: TestClient,
    db_session: Session,
) -> None:
    _, share = add_fund(db_session)
    add_nav(db_session, share, date(2026, 7, 30), "1.00")
    add_nav(db_session, share, date(2026, 7, 31), "1.02")
    db_session.commit()

    response = client.get(
        "/api/dashboards/active-tech/returns?pool=CORE&period=MTD&as_of=2026-08-04"
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["baseline_date"] == "2026-07-31"
    assert item["end_date"] == "2026-07-31"
    assert item["return_pct"] == "0E-8"


def test_active_tech_qtd_uses_prior_quarter_baseline(
    client: TestClient,
    db_session: Session,
) -> None:
    _, share = add_fund(db_session)
    add_nav(db_session, share, date(2026, 6, 30), "1.00")
    add_nav(db_session, share, date(2026, 7, 1), "1.03")
    db_session.commit()

    response = client.get(
        "/api/dashboards/active-tech/returns?pool=CORE&period=QTD&as_of=2026-07-01"
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["baseline_date"] == "2026-06-30"
    assert item["return_pct"] == "3.00000000"


def test_active_tech_return_marks_missing_baseline(
    client: TestClient,
    db_session: Session,
) -> None:
    _, share = add_fund(db_session)
    add_nav(db_session, share, date(2026, 8, 1), "1.02")
    db_session.commit()

    response = client.get(
        "/api/dashboards/active-tech/returns?pool=CORE&period=MTD&as_of=2026-08-01"
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["return_pct"] is None
    assert item["status"] == "MISSING_BASELINE"


def test_active_tech_return_marks_stale_nav_and_exposes_sync_date(
    client: TestClient,
    db_session: Session,
) -> None:
    _, share = add_fund(db_session)
    add_nav(db_session, share, date(2026, 7, 31), "1.00")
    add_nav(db_session, share, date(2026, 8, 1), "1.01")
    db_session.add(
        DataOperation(
            operation="sync-daily",
            status="succeeded",
            active_slot=None,
            fund_codes=["002891"],
            lookback_days=10,
            report_year=2026,
            report_quarter=2,
            stage_completed=1,
            stage_total=1,
            run_ids=[],
            finished_at=datetime(2026, 8, 10, 1, tzinfo=UTC),
        )
    )
    db_session.commit()

    response = client.get(
        "/api/dashboards/active-tech/returns?pool=CORE&period=DAILY&as_of=2026-08-10"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sync_date"] == "2026-08-10"
    assert payload["stale_fund_count"] == 1
    assert payload["items"][0]["status"] == "STALE"
    assert payload["items"][0]["nav_lag_days"] == 9


def test_active_tech_return_uses_one_representative_share(
    client: TestClient,
    db_session: Session,
) -> None:
    fund, representative = add_fund(db_session)
    other = FundShare(
        fund_contract_id=fund.id,
        share_code="002892",
        share_class="C",
        currency="CNY",
    )
    db_session.add(other)
    db_session.flush()
    add_nav(db_session, representative, date(2026, 7, 31), "1.00")
    add_nav(db_session, representative, date(2026, 8, 1), "1.10")
    add_nav(db_session, other, date(2026, 7, 31), "1.00")
    add_nav(db_session, other, date(2026, 8, 1), "2.00")
    db_session.commit()

    response = client.get(
        "/api/dashboards/active-tech/returns?pool=CORE&period=DAILY&as_of=2026-08-01"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["fund_count"] == 1
    assert payload["comparable_fund_count"] == 1
    assert payload["items"][0]["share_code"] == "002891"
    assert payload["items"][0]["return_pct"] == "10.00000000"


def test_active_tech_return_uses_latest_date_shared_by_every_nav_ready_fund(
    client: TestClient,
    db_session: Session,
) -> None:
    _, first_share = add_fund(db_session)
    _, second_share = add_fund(db_session, code="005698", name="第二只科技基金")
    add_nav(db_session, first_share, date(2026, 7, 29), "0.90")
    add_nav(db_session, first_share, date(2026, 7, 30), "1.00")
    add_nav(db_session, first_share, date(2026, 7, 31), "1.10")
    add_nav(db_session, first_share, date(2026, 8, 2), "1.20")
    add_nav(db_session, second_share, date(2026, 7, 29), "1.80")
    add_nav(db_session, second_share, date(2026, 7, 30), "2.00")
    add_nav(db_session, second_share, date(2026, 8, 1), "2.20")
    db_session.commit()

    response = client.get(
        "/api/dashboards/active-tech/returns?pool=CORE&period=DAILY&as_of=2026-08-01"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["common_comparable_date"] == "2026-07-30"
    assert {item["end_date"] for item in payload["items"]} == {"2026-07-30"}
    assert {item["baseline_date"] for item in payload["items"]} == {"2026-07-29"}


def test_active_tech_return_marks_missing_nav(
    client: TestClient,
    db_session: Session,
) -> None:
    add_fund(db_session)
    db_session.commit()

    response = client.get(
        "/api/dashboards/active-tech/returns?pool=CORE&period=DAILY&as_of=2026-08-01"
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "MISSING_NAV"


def test_active_tech_regions_aggregates_basis_and_reports_missing_coverage(
    client: TestClient,
    db_session: Session,
) -> None:
    covered_fund, _ = add_fund(db_session)
    add_fund(db_session, code="005698", name="缺失地区基金")
    report = FundReport(
        fund_contract_id=covered_fund.id,
        report_type="QUARTERLY",
        report_year=2026,
        report_quarter=2,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        source_provider="FIXTURE",
        parse_status="parsed",
        parse_confidence=Decimal("0.95"),
    )
    db_session.add(report)
    db_session.flush()
    for basis, us_pct, hk_pct in (
        ("DIRECT", "60", "20"),
        ("LOOKTHROUGH", "70", "15"),
    ):
        db_session.add_all(
            [
                ReportCountryAllocation(
                    fund_report_id=report.id,
                    country_name_raw="美国",
                    country_name_normalized="US",
                    exposure_basis=basis,
                    nav_pct=Decimal(us_pct),
                    rank=1,
                    source_section="国家分布",
                    raw_row={},
                ),
                ReportCountryAllocation(
                    fund_report_id=report.id,
                    country_name_raw="中国香港",
                    country_name_normalized="HK",
                    exposure_basis=basis,
                    nav_pct=Decimal(hk_pct),
                    rank=2,
                    source_section="国家分布",
                    raw_row={},
                ),
                ReportCountryAllocation(
                    fund_report_id=report.id,
                    country_name_raw="中国台湾",
                    country_name_normalized="TW",
                    exposure_basis=basis,
                    nav_pct=Decimal("5"),
                    rank=3,
                    source_section="国家分布",
                    raw_row={},
                ),
            ]
        )
    db_session.commit()

    response = client.get(
        "/api/dashboards/active-tech/regions"
        "?pool=CORE&basis=LOOKTHROUGH&year=2026&quarter=2"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["covered_fund_count"] == 1
    assert payload["missing_fund_count"] == 1
    assert payload["available_quarters"] == [
        {"year": 2026, "quarter": 2, "period_end": "2026-06-30"}
    ]
    assert payload["average_distribution"][:2] == [
        {"country": "美国", "average_nav_pct": "70.00000000", "covered_fund_count": 1},
        {"country": "日本", "average_nav_pct": "0", "covered_fund_count": 0},
    ]
    assert payload["average_distribution"][3] == {
        "country": "中国香港",
        "average_nav_pct": "15.00000000",
        "covered_fund_count": 1,
    }
    assert payload["average_distribution"][-2] == {
        "country": "其他分类",
        "average_nav_pct": "5.00000000",
        "covered_fund_count": 1,
    }
    assert payload["average_distribution"][-1] == {
        "country": "未披露",
        "average_nav_pct": "10.00000000",
        "covered_fund_count": 1,
    }
    assert [item["country"] for item in payload["funds"][0]["allocations"]] == [
        "美国",
        "日本",
        "韩国",
        "中国香港",
        "中国内地",
        "其他分类",
        "未披露",
    ]
    assert payload["missing"][0]["reason"] == "MISSING_REPORT"


def test_active_tech_regions_requires_complete_quarter_selector(
    client: TestClient,
) -> None:
    response = client.get("/api/dashboards/active-tech/regions?year=2026")

    assert response.status_code == 422
    assert response.json()["detail"] == "year and quarter must be provided together"
