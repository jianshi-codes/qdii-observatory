from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.analysis import analyze_disclosed_holdings, export_evidence
from backend.app.models import (
    DailyFundNav,
    FundContract,
    FundReport,
    FundShare,
    ReportDerivedMetrics,
)


def test_disclosed_holdings_baseline_is_traceable_and_neutral(
    db_session: Session, tmp_path: Path
) -> None:
    fund = FundContract(
        canonical_name="Synthetic Active Fund",
        manager_name="Example Manager",
        representative_code="654321",
        strategy_type="ACTIVE",
    )
    db_session.add(fund)
    db_session.flush()
    share = FundShare(
        fund_contract_id=fund.id,
        share_code="654321",
        currency="CNY",
    )
    db_session.add(share)
    db_session.flush()
    report = FundReport(
        fund_contract_id=fund.id,
        report_type="QUARTERLY",
        report_year=2024,
        report_quarter=4,
        period_start=date(2024, 10, 1),
        period_end=date(2024, 12, 31),
        public_available_at=datetime(2025, 1, 20, tzinfo=UTC),
        source_provider="SYNTHETIC",
        parse_status="PARSED",
    )
    db_session.add(report)
    db_session.flush()
    db_session.add(
        ReportDerivedMetrics(
            fund_report_id=report.id,
            tech_scope="UNKNOWN",
            undisclosed_equity_pct=Decimal("35"),
            unresolved_fund_weight_pct=Decimal("5"),
        )
    )
    start = date(2025, 1, 1)
    actual_values = ["0.10", "0.20", "-0.10", "0.30", "0.15", "-0.05"]
    for offset, value in enumerate(actual_values):
        db_session.add(
            DailyFundNav(
                fund_share_id=share.id,
                nav_date=start + timedelta(days=offset),
                unit_nav=Decimal("1") + Decimal(offset) / Decimal("100"),
                published_daily_return_pct=Decimal(value),
                source_provider="SYNTHETIC",
                raw_payload_hash=str(offset).zfill(64),
            )
        )
    db_session.commit()
    series = tmp_path / "estimated.csv"
    series.write_text(
        "date,estimated_return_pct\n"
        + "".join(
            f"{start + timedelta(days=index)},{value}\n"
            for index, value in enumerate(actual_values)
        ),
        encoding="utf-8",
    )
    config = tmp_path / "proxies.yaml"
    config.write_text(
        f'funds:\n  "654321":\n    estimated_returns_file: "{series}"\n',
        encoding="utf-8",
    )

    result = analyze_disclosed_holdings(
        db_session,
        fund_code="654321",
        proxy_config=config,
        latest_report=True,
    )

    assert result.model == "DISCLOSED_HOLDINGS_BASELINE"
    assert result.analysis_start_date == date(2025, 1, 1)
    assert result.mode == "EX_POST"
    assert result.coverage == Decimal("1.0000")
    assert result.consistency_status == "CONSISTENT"
    assert result.undisclosed_equity_pct == Decimal("35")
    assert result.unresolved_fund_weight_pct == Decimal("5")
    evidence = export_evidence(result, tmp_path / "evidence", "PUBLIC")
    assert '"fund_code": "REDACTED"' in evidence.read_text(encoding="utf-8")
