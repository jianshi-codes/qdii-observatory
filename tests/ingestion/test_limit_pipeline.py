from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.ingestion.limit_pipeline import sync_purchase_limits
from backend.app.ingestion.providers.base import PurchaseLimitRecord, PurchaseLimitSnapshot
from backend.app.models import (
    DailyPurchaseLimit,
    DataQualityIssue,
    FundContract,
    FundShare,
    SourceArtifact,
)

OBSERVED_AT = datetime(2026, 7, 31, 8, tzinfo=UTC)


def _selected_share(session: Session) -> FundShare:
    contract = FundContract(
        canonical_name="测试QDII基金",
        manager_name="测试管理人",
        representative_code="000834",
        is_user_selected=True,
    )
    session.add(contract)
    session.flush()
    share = FundShare(
        fund_contract_id=contract.id,
        share_code="000834",
        share_class="A",
        currency="CNY",
    )
    session.add(share)
    session.commit()
    return share


def _record(
    share_code: str,
    *,
    channel_type: str,
    channel_key: str,
    channel_name: str,
    amount: str,
) -> PurchaseLimitRecord:
    return PurchaseLimitRecord(
        share_code=share_code,
        channel_type=channel_type,
        channel_key=channel_key,
        channel_name=channel_name,
        business_type="PURCHASE",
        availability_state="OPEN",
        cap_state="LIMITED",
        limit_amount=Decimal(amount),
        currency="CNY",
        limit_basis="PER_ACCOUNT_PER_DAY",
        limit_scope="PER_SHARE",
        effective_from=date(2026, 6, 4),
        effective_to=None,
        source_published_at=datetime(2026, 6, 3, tzinfo=UTC),
        raw_text=f"{channel_name}每日限额{amount}元",
        confidence=Decimal("0.9900"),
    )


class FixtureDirectProvider:
    name = "FIXTURE_OFFICIAL_LIMIT"
    version = "v1"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, tuple[str, ...], frozenset[str], dict[str, str] | None]] = []

    def fetch(
        self,
        fund_code: str,
        share_codes: tuple[str, ...],
        *,
        exchange_traded_codes: frozenset[str] = frozenset(),
        share_currencies: dict[str, str] | None = None,
    ) -> PurchaseLimitSnapshot:
        self.calls.append((fund_code, share_codes, exchange_traded_codes, share_currencies))
        if self.fail:
            raise RuntimeError("fixture official source unavailable")
        return PurchaseLimitSnapshot(
            provider_name=self.name,
            provider_version=self.version,
            observed_at=OBSERVED_AT,
            records=tuple(
                _record(
                    share_code,
                    channel_type="DIRECT",
                    channel_key="DIRECT",
                    channel_name="基金管理人直销",
                    amount="100",
                )
                for share_code in share_codes
            ),
            raw_payload=b"official-limit-fixture",
            source_url="https://example.test/official-limit.pdf",
            mime_type="application/pdf",
            artifact_type="PURCHASE_LIMIT_NOTICE_PDF",
        )


class FixtureDistributionProvider:
    name = "FIXTURE_NAMED_DISTRIBUTOR_LIMIT"
    version = "v1"

    def fetch(self, share_code: str) -> PurchaseLimitSnapshot:
        return PurchaseLimitSnapshot(
            provider_name=self.name,
            provider_version=self.version,
            observed_at=OBSERVED_AT,
            records=(
                _record(
                    share_code,
                    channel_type="DISTRIBUTION",
                    channel_key="EASTMONEY_TIANTIAN",
                    channel_name="天天基金",
                    amount="10",
                ),
            ),
            raw_payload=f"named-distributor-limit-{share_code}".encode(),
            source_url=f"https://example.test/distributor/{share_code}",
            mime_type="text/html",
            artifact_type="PURCHASE_LIMIT_HTML",
        )


def test_purchase_limit_pipeline_stores_two_channels_artifacts_and_is_idempotent(
    db_session: Session,
    tmp_path: Path,
) -> None:
    share = _selected_share(db_session)
    direct = FixtureDirectProvider()
    distribution = FixtureDistributionProvider()
    raw_root = tmp_path / "raw"

    first_run = sync_purchase_limits(db_session, direct, distribution, raw_root)
    db_session.expire_all()
    first_rows = list(
        db_session.scalars(
            select(DailyPurchaseLimit).order_by(DailyPurchaseLimit.channel_type)
        ).all()
    )
    first_ids = {
        (row.channel_type, row.channel_key, row.source_provider): row.id for row in first_rows
    }

    assert first_run.status == "succeeded"
    assert (first_run.records_seen, first_run.records_written, first_run.records_failed) == (
        2,
        2,
        0,
    )
    assert direct.calls == [("000834", ("000834",), frozenset(), {"000834": "CNY"})]
    assert {row.channel_type for row in first_rows} == {"DIRECT", "DISTRIBUTION"}
    assert {row.daily_limit_amount for row in first_rows} == {
        Decimal("10.000000"),
        Decimal("100.000000"),
    }
    assert all(row.fund_share_id == share.id for row in first_rows)
    assert all(row.source_artifact_id is not None for row in first_rows)
    assert all(row.raw_payload_hash == row.source_artifact.sha256 for row in first_rows)
    assert all((raw_root / row.source_artifact.local_path).is_file() for row in first_rows)
    assert db_session.scalar(select(func.count()).select_from(SourceArtifact)) == 2

    second_run = sync_purchase_limits(db_session, direct, distribution, raw_root)
    db_session.expire_all()
    second_rows = list(db_session.scalars(select(DailyPurchaseLimit)).all())

    assert second_run.status == "succeeded"
    assert {
        (row.channel_type, row.channel_key, row.source_provider): row.id for row in second_rows
    } == first_ids
    assert len(second_rows) == 2
    assert db_session.scalar(select(func.count()).select_from(SourceArtifact)) == 2
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(DataQualityIssue)
            .where(DataQualityIssue.status == "OPEN")
        )
        == 0
    )


def test_purchase_limit_pipeline_isolates_one_source_failure_and_records_dq(
    db_session: Session,
    tmp_path: Path,
) -> None:
    share = _selected_share(db_session)

    run = sync_purchase_limits(
        db_session,
        FixtureDirectProvider(fail=True),
        FixtureDistributionProvider(),
        tmp_path / "raw",
    )
    db_session.expire_all()

    rows = list(db_session.scalars(select(DailyPurchaseLimit)).all())
    assert run.status == "partial"
    assert run.records_failed == 1
    assert len(rows) == 1
    assert rows[0].fund_share_id == share.id
    assert rows[0].channel_type == "DISTRIBUTION"
    assert rows[0].source_provider == "FIXTURE_NAMED_DISTRIBUTOR_LIMIT"
    assert rows[0].source_artifact_id is not None

    issues = {
        issue.issue_code: issue
        for issue in db_session.scalars(
            select(DataQualityIssue).where(DataQualityIssue.status == "OPEN")
        ).all()
    }
    assert set(issues) == {
        "SALES_LIMIT_SYNC_FAILED",
        "SALES_LIMIT_COVERAGE_INCOMPLETE",
    }
    assert issues["SALES_LIMIT_SYNC_FAILED"].fund_share_id == share.id
    assert issues["SALES_LIMIT_SYNC_FAILED"].details == {
        "failures": [
            {
                "provider": "FIXTURE_OFFICIAL_LIMIT",
                "exception_type": "RuntimeError",
                "message": "fixture official source unavailable",
            }
        ]
    }
    assert issues["SALES_LIMIT_COVERAGE_INCOMPLETE"].details["missing_channels"] == ["DIRECT"]
