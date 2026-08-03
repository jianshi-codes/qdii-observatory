from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models import (
    DailyFundNav,
    DailyPurchaseLimit,
    FundContract,
    FundRelation,
    FundReport,
    FundShare,
    ReportCountryAllocation,
    ReportFundHolding,
    SourceArtifact,
)


def test_contract_share_report_and_relation_boundaries(db_session: Session) -> None:
    feeder = FundContract(
        canonical_name="大成纳斯达克100ETF联接",
        manager_name="大成基金",
        representative_code="000834",
        wrapper_type="ETF_FEEDER",
    )
    target = FundContract(
        canonical_name="大成纳斯达克100ETF",
        manager_name="大成基金",
        representative_code="159513",
        wrapper_type="ETF",
        is_user_selected=False,
        is_dependency=True,
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
    report = FundReport(
        fund_contract_id=feeder.id,
        report_type="QUARTERLY",
        report_year=2026,
        report_quarter=2,
        period_end=date(2026, 6, 30),
        source_provider="CSRC_EID",
        parse_status="PARSED",
    )
    db_session.add_all([feeder_share, target_share, report])
    db_session.flush()
    db_session.add_all(
        [
            FundRelation(
                source_fund_contract_id=feeder.id,
                target_fund_contract_id=target.id,
                relation_type="FEEDER_TO_TARGET_ETF",
                report_id=report.id,
                weight_nav_pct=Decimal("94.12345678"),
                confidence=Decimal("0.9900"),
            ),
            FundRelation(
                source_fund_contract_id=feeder.id,
                external_target_name="External ETF",
                external_target_code="EXT1",
                relation_type="REPORT_FUND_HOLDING",
                report_id=report.id,
                weight_nav_pct=Decimal("1.10000000"),
            ),
            ReportFundHolding(
                fund_report_id=report.id,
                resolved_fund_contract_id=target.id,
                fund_code_raw="159513",
                fund_name_raw="大成纳斯达克100交易型开放式指数证券投资基金",
                fund_name_normalized="大成纳斯达克100ETF",
                is_unresolved=False,
                fair_value_cny=Decimal("123456789.123456"),
                nav_pct=Decimal("94.12345678"),
                rank=1,
                source_section="前十名基金投资明细",
                raw_row={"code": "159513"},
                parse_confidence=Decimal("0.9900"),
            ),
        ]
    )
    db_session.commit()

    assert feeder.representative_code == "000834"
    assert feeder_share.share_code == "000834"
    assert len(feeder.reports) == 1
    assert (
        len(
            db_session.query(FundRelation)
            .filter(FundRelation.source_fund_contract_id == feeder.id)
            .all()
        )
        == 2
    )


def test_database_precision_and_idempotency_constraints(db_session: Session) -> None:
    fund = FundContract(
        canonical_name="测试基金",
        manager_name="测试管理人",
        representative_code="000001",
    )
    db_session.add(fund)
    db_session.flush()
    share = FundShare(
        fund_contract_id=fund.id,
        share_code="000001",
        currency="CNY",
    )
    db_session.add(share)
    db_session.flush()
    db_session.add(
        DailyFundNav(
            fund_share_id=share.id,
            nav_date=date(2026, 7, 30),
            unit_nav=Decimal("1.12345678"),
            accumulated_nav=Decimal("2.23456789"),
            source_provider="FIXTURE",
            raw_payload_hash="a" * 64,
        )
    )
    db_session.commit()
    stored = db_session.query(DailyFundNav).one()
    assert stored.unit_nav == Decimal("1.12345678")
    assert stored.accumulated_nav == Decimal("2.23456789")

    db_session.add(
        DailyFundNav(
            fund_share_id=share.id,
            nav_date=date(2026, 7, 30),
            unit_nav=Decimal("1.20000000"),
            source_provider="FIXTURE",
            raw_payload_hash="b" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_invalid_codes_and_unexplained_empty_rows_are_rejected(
    db_session: Session,
) -> None:
    db_session.add(
        FundContract(
            canonical_name="Bad code",
            manager_name="Manager",
            representative_code="12345",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    fund = FundContract(
        canonical_name="Valid",
        manager_name="Manager",
        representative_code="123456",
    )
    db_session.add(fund)
    db_session.flush()
    report = FundReport(
        fund_contract_id=fund.id,
        report_type="QUARTERLY",
        report_year=2026,
        report_quarter=2,
        period_end=date(2026, 6, 30),
        source_provider="FIXTURE",
        parse_status="VALID_EMPTY",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(
        ReportCountryAllocation(
            fund_report_id=report.id,
            country_name_raw="美国",
            country_name_normalized="US",
            nav_pct=Decimal("-0.1"),
            source_section="国家分布",
            raw_row={},
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_purchase_limit_semantics_idempotency_and_source_traceability(
    db_session: Session,
) -> None:
    fund = FundContract(
        canonical_name="限额测试基金",
        manager_name="测试管理人",
        representative_code="123457",
    )
    db_session.add(fund)
    db_session.flush()
    share = FundShare(fund_contract_id=fund.id, share_code="123457", currency="CNY")
    db_session.add(share)
    db_session.flush()
    artifact = SourceArtifact(
        fund_contract_id=fund.id,
        fund_share_id=share.id,
        artifact_type="PURCHASE_LIMIT_HTML",
        source_provider="FUND_MANAGER",
        source_url="https://example.test/limit",
        local_path="purchase-limits/123457.html",
        mime_type="text/html",
        sha256="a" * 64,
        byte_size=100,
        metadata_json={},
    )
    db_session.add(artifact)
    db_session.flush()
    row = DailyPurchaseLimit(
        fund_share_id=share.id,
        snapshot_date=date(2026, 7, 31),
        channel_type="DIRECT",
        channel_key="FUND_MANAGER_DIRECT",
        channel_name="基金管理人直销",
        business_type="PURCHASE",
        availability_state="PAUSED",
        cap_state="LIMITED",
        daily_limit_amount=Decimal("1000"),
        currency="CNY",
        limit_basis="PER_ACCOUNT_PER_DAY",
        share_scope="ALL_SHARES_COMBINED",
        effective_from=date(2026, 7, 1),
        source_provider="FUND_MANAGER",
        source_url="https://example.test/limit",
        source_artifact_id=artifact.id,
        raw_payload_hash="a" * 64,
        raw_text="A/C份额合并限额，当前暂停申购",
        confidence=Decimal("0.9900"),
    )
    db_session.add(row)
    db_session.commit()

    assert share.purchase_limits == [row]
    assert row.availability_state == "PAUSED"
    assert row.cap_state == "LIMITED"
    assert row.share_scope == "ALL_SHARES_COMBINED"
    artifact_foreign_key = next(
        foreign_key
        for foreign_key in DailyPurchaseLimit.__table__.foreign_keys
        if foreign_key.parent.name == "source_artifact_id"
    )
    assert artifact_foreign_key.ondelete == "RESTRICT"

    db_session.add(
        DailyPurchaseLimit(
            fund_share_id=share.id,
            snapshot_date=row.snapshot_date,
            channel_type=row.channel_type,
            channel_key=row.channel_key,
            channel_name=row.channel_name,
            business_type=row.business_type,
            availability_state="OPEN",
            cap_state="LIMITED",
            daily_limit_amount=Decimal("2000"),
            currency="CNY",
            limit_basis=row.limit_basis,
            share_scope=row.share_scope,
            source_provider=row.source_provider,
            source_url=row.source_url,
            source_artifact_id=artifact.id,
            raw_payload_hash="b" * 64,
            raw_text="重复的同日同来源业务键",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    db_session.add(
        DailyPurchaseLimit(
            fund_share_id=share.id,
            snapshot_date=date(2026, 8, 1),
            channel_type="DIRECT",
            channel_key="FUND_MANAGER_DIRECT",
            channel_name="基金管理人直销",
            business_type="PURCHASE",
            availability_state="OPEN",
            cap_state="UNLIMITED",
            daily_limit_amount=Decimal("1"),
            currency="CNY",
            limit_basis="PER_ACCOUNT_PER_DAY",
            share_scope="PER_SHARE",
            source_provider="FUND_MANAGER",
            source_url="https://example.test/limit",
            source_artifact_id=artifact.id,
            raw_payload_hash="c" * 64,
            raw_text="无上限不应带金额",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_metadata_contains_all_domain_tables() -> None:
    expected = {
        "fund_contract",
        "fund_share",
        "fund_relation",
        "fund_report",
        "exposure_family",
        "fund_exposure_family",
        "report_asset_allocation",
        "report_country_allocation",
        "report_industry_allocation",
        "report_security_holding",
        "report_fund_holding",
        "report_derived_metrics",
        "daily_fund_nav",
        "daily_exchange_price",
        "daily_exchange_rate",
        "daily_purchase_limit",
        "daily_fund_fee",
        "portfolio_position",
        "portfolio_cash_flow",
        "ingestion_run",
        "data_operation",
        "source_artifact",
        "data_quality_issue",
    }
    assert expected == set(inspect(FundContract.metadata).tables)
