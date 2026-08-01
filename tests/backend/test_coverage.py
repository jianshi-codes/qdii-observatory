from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from backend.app.coverage import (
    COVERAGE_COLUMNS,
    CoverageError,
    build_coverage_rows,
    generate_coverage,
)
from backend.app.models import (
    FundContract,
    FundRelation,
    FundReport,
    ReportCountryAllocation,
    ReportDerivedMetrics,
    ReportFundHolding,
    ReportIndustryAllocation,
    ReportSecurityHolding,
)


def _seed_coverage(session: Session) -> list[FundContract]:
    funds = [
        FundContract(
            canonical_name=f"测试基金{index:02d}",
            manager_name="测试基金管理人",
            representative_code=f"{index:06d}",
            wrapper_type="ETF_FEEDER" if index == 1 else "DIRECT",
        )
        for index in range(1, 5)
    ]
    session.add_all(funds)
    session.flush()

    parsed = FundReport(
        fund_contract_id=funds[0].id,
        report_type="QUARTERLY",
        report_year=2026,
        report_quarter=2,
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
        source_provider="FIXTURE",
        source_page_url="https://example.test/fund/000001",
        document_url="https://example.test/fund/000001.pdf",
        local_document_path="reports/000001.pdf",
        sha256="a" * 64,
        parse_status="parsed",
        parse_confidence=Decimal("0.9800"),
    )
    failed = FundReport(
        fund_contract_id=funds[1].id,
        report_type="QUARTERLY",
        report_year=2026,
        report_quarter=2,
        period_end=date(2026, 6, 30),
        source_provider="FIXTURE",
        parse_status="failed_with_reason",
        parse_error="Identity mismatch",
    )
    valid_empty = FundReport(
        fund_contract_id=funds[2].id,
        report_type="QUARTERLY",
        report_year=2026,
        report_quarter=2,
        period_end=date(2026, 6, 30),
        source_provider="FIXTURE",
        local_document_path="reports/000003.pdf",
        sha256="c" * 64,
        parse_status="valid_empty",
        parse_confidence=Decimal("1.0000"),
    )
    session.add_all([parsed, failed, valid_empty])
    session.flush()

    common = {
        "fund_report_id": parsed.id,
        "fair_value_cny": Decimal("1000.000000"),
        "nav_pct": Decimal("80.00000000"),
        "rank": 1,
        "source_section": "fixture",
        "raw_row": {},
        "parse_confidence": Decimal("0.9800"),
    }
    session.add_all(
        [
            ReportCountryAllocation(
                **common,
                country_name_raw="美国",
                country_name_normalized="US",
                exposure_basis="DIRECT",
            ),
            ReportCountryAllocation(
                **common,
                country_name_raw="美国",
                country_name_normalized="US",
                exposure_basis="LOOKTHROUGH",
            ),
            ReportIndustryAllocation(
                **common,
                industry_name_raw="信息技术",
                industry_name_normalized="INFORMATION_TECHNOLOGY",
                exposure_basis="DIRECT",
            ),
            ReportIndustryAllocation(
                **common,
                industry_name_raw="信息技术",
                industry_name_normalized="INFORMATION_TECHNOLOGY",
                exposure_basis="LOOKTHROUGH",
            ),
            ReportSecurityHolding(
                **common,
                security_code_raw="NVDA",
                security_name_raw="NVIDIA",
                security_name_normalized="NVIDIA",
                security_type="COMMON_STOCK",
                exposure_basis="DIRECT",
            ),
            ReportFundHolding(
                **common,
                resolved_fund_contract_id=funds[1].id,
                fund_code_raw=funds[1].representative_code,
                fund_name_raw=funds[1].canonical_name,
                fund_name_normalized=funds[1].canonical_name,
                is_unresolved=False,
                exposure_basis="DIRECT",
            ),
            ReportDerivedMetrics(
                fund_report_id=parsed.id,
                lookthrough_coverage_pct=Decimal("80.00000000"),
                unresolved_fund_weight_pct=Decimal("0"),
                max_lookthrough_depth=1,
                data_as_of=date(2026, 6, 30),
            ),
            FundRelation(
                source_fund_contract_id=funds[0].id,
                target_fund_contract_id=funds[1].id,
                relation_type="FEEDER_TO_TARGET_ETF",
                report_id=parsed.id,
                weight_nav_pct=Decimal("80.00000000"),
            ),
        ]
    )
    session.commit()
    return funds


def test_coverage_has_one_explicit_deterministic_row_per_selected_fund(
    db_session: Session, tmp_path: Path
) -> None:
    _seed_coverage(db_session)
    result = generate_coverage(db_session, tmp_path, year=2026, quarter=2)
    first_csv = result.csv_path.read_bytes()
    first_markdown = result.markdown_path.read_bytes()
    repeated = generate_coverage(db_session, tmp_path, year=2026, quarter=2)

    assert len(result.rows) == 4
    assert first_csv == repeated.csv_path.read_bytes()
    assert first_markdown == repeated.markdown_path.read_bytes()
    assert [row.representative_code for row in result.rows] == sorted(
        row.representative_code for row in result.rows
    )

    parsed, failed, valid_empty, missing = result.rows[:4]
    assert parsed.report_status == "parsed"
    assert parsed.target_fund_code == "000002"
    assert parsed.direct_country_available is True
    assert parsed.direct_industry_available is True
    assert parsed.stock_holding_count == 1
    assert parsed.fund_holding_count == 1
    assert parsed.lookthrough_status == "resolved"
    assert failed.failure_reason == "Identity mismatch"
    assert valid_empty.parsed is True
    assert missing.report_status == "unresolved"
    assert missing.failure_reason == "No fund_report row for 2026 Q2."

    csv_rows = list(csv.DictReader(io.StringIO(first_csv.decode("utf-8"))))
    assert len(csv_rows) == 4
    assert tuple(csv_rows[0]) == COVERAGE_COLUMNS
    assert csv_rows[0]["report_found"] == "true"
    assert csv_rows[3]["report_found"] == "false"
    markdown = first_markdown.decode("utf-8")
    assert "用户选择基金：4" in markdown
    assert "已解析或有效空表：2" in markdown


def test_coverage_requires_at_least_one_enabled_fund(db_session: Session) -> None:
    with pytest.raises(CoverageError, match="at least one"):
        build_coverage_rows(db_session, year=2026, quarter=2)
