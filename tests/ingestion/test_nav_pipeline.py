from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.ingestion.nav_pipeline import sync_exchange_prices, sync_nav
from backend.app.ingestion.providers.base import ExchangePriceRecord
from backend.app.ingestion.providers.nav import EastmoneyNavProvider
from backend.app.ingestion.runs import record_issue
from backend.app.models import (
    DailyFundNav,
    DataQualityIssue,
    FundContract,
    FundShare,
    SourceArtifact,
)


def _selected_share(session: Session) -> FundShare:
    contract = FundContract(
        canonical_name="测试基金",
        manager_name="测试管理人",
        representative_code="017653",
        is_user_selected=True,
    )
    session.add(contract)
    session.flush()
    share = FundShare(
        fund_contract_id=contract.id,
        share_code="017653",
        share_class="A",
        currency="CNY",
    )
    session.add(share)
    session.commit()
    return share


def _nav_rows(session: Session) -> list[DailyFundNav]:
    return list(session.scalars(select(DailyFundNav).order_by(DailyFundNav.nav_date)))


def test_nav_sync_paginates_upserts_recalculates_and_is_idempotent(
    db_session: Session,
    fixture_nav_provider: tuple[EastmoneyNavProvider, Any],
    tmp_path: Path,
) -> None:
    share = _selected_share(db_session)
    provider, http = fixture_nav_provider
    raw_root = tmp_path / "raw"
    record_issue(
        db_session,
        fund_contract_id=share.fund_contract_id,
        fund_share_id=share.id,
        issue_code="NAV_SYNC_FAILED",
        severity="ERROR",
        message="prior failure",
        details={},
    )
    db_session.commit()

    first_run = sync_nav(
        db_session,
        provider,
        raw_root,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 3),
        share_codes={share.share_code},
        page_size=2,
    )
    db_session.expire_all()
    first_rows = _nav_rows(db_session)
    first_ids = {row.nav_date: row.id for row in first_rows}

    assert first_run.status == "succeeded"
    issue = db_session.scalar(
        select(DataQualityIssue).where(DataQualityIssue.issue_code == "NAV_SYNC_FAILED")
    )
    assert issue is not None
    assert issue.status == "RESOLVED"
    assert (
        first_run.records_seen,
        first_run.records_written,
        first_run.records_failed,
    ) == (1, 3, 0)
    assert http.requested_pages == [1, 2]
    assert [row.nav_date for row in first_rows] == [
        date(2024, 1, 1),
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]
    assert [row.calculated_daily_return_pct for row in first_rows] == [
        None,
        Decimal("10.00000000"),
        Decimal("10.00000000"),
    ]

    rows_by_date = {row["FSRQ"]: row for row in http.documents[1]["Data"]["LSJZList"]}
    rows_by_date["2024-01-02"].update({"DWJZ": "1.0500", "LJJZ": "1.0500", "JZZZL": "5.0000"})
    rows_by_date["2024-01-03"]["JZZZL"] = "15.2381"
    http.requested_pages.clear()

    revised_run = sync_nav(
        db_session,
        provider,
        raw_root,
        share_codes={share.share_code},
        page_size=2,
    )
    db_session.expire_all()
    revised_rows = _nav_rows(db_session)

    assert revised_run.status == "succeeded"
    assert http.requested_pages == [1, 2]
    assert {row.nav_date: row.id for row in revised_rows} == first_ids
    assert len(revised_rows) == 3
    assert revised_rows[1].unit_nav == Decimal("1.05000000")
    assert revised_rows[1].calculated_daily_return_pct == Decimal("5.00000000")
    assert revised_rows[2].calculated_daily_return_pct == Decimal("15.23809524")
    assert db_session.scalar(select(func.count()).select_from(SourceArtifact)) == 3

    third_run = sync_nav(
        db_session,
        provider,
        raw_root,
        share_codes={share.share_code},
        page_size=2,
    )
    db_session.expire_all()

    assert third_run.status == "succeeded"
    assert db_session.scalar(select(func.count()).select_from(DailyFundNav)) == 3
    assert {row.nav_date: row.id for row in _nav_rows(db_session)} == first_ids
    assert db_session.scalar(select(func.count()).select_from(SourceArtifact)) == 3


def test_nav_sync_records_an_explicit_failure_when_provider_has_no_rows(
    db_session: Session,
    fixture_nav_provider: tuple[EastmoneyNavProvider, Any],
    tmp_path: Path,
) -> None:
    share = _selected_share(db_session)
    provider, http = fixture_nav_provider
    http.documents[1]["TotalCount"] = 0
    http.documents[1]["PageSize"] = 20
    http.documents[1]["Data"]["LSJZList"] = []

    run = sync_nav(
        db_session,
        provider,
        tmp_path / "raw",
        share_codes={share.share_code},
        page_size=20,
    )

    issue = db_session.scalar(
        select(DataQualityIssue).where(DataQualityIssue.issue_code == "NAV_SYNC_FAILED")
    )
    assert run.status == "partial"
    assert run.records_failed == 1
    assert issue is not None
    assert issue.status == "OPEN"
    assert "no records" in issue.message


def test_market_sync_records_an_explicit_failure_when_provider_has_no_rows(
    db_session: Session, tmp_path: Path
) -> None:
    share = _selected_share(db_session)
    share.is_exchange_traded = True
    db_session.commit()

    class EmptyMarketProvider:
        name = "EMPTY_MARKET"
        version = "test-v1"

        def fetch(
            self, share_code: str, start_date: date, end_date: date
        ) -> tuple[bytes, tuple[ExchangePriceRecord, ...], str]:
            return b"{}", (), f"https://example.invalid/{share_code}"

    run = sync_exchange_prices(
        db_session,
        EmptyMarketProvider(),  # type: ignore[arg-type]
        tmp_path / "raw",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 31),
    )

    issue = db_session.scalar(
        select(DataQualityIssue).where(DataQualityIssue.issue_code == "MARKET_PRICE_SYNC_FAILED")
    )
    assert run.status == "partial"
    assert run.records_failed == 1
    assert issue is not None
    assert "no records" in issue.message
