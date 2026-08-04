from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from backend.app.ingestion.parser import (
    ParsedQuarterlyReport,
    ReportParseError,
    _append_security,
    _append_unclassified_industry_note,
    _classify_table,
    _explicit_empty_sections,
)
from backend.app.ingestion.report_pipeline import _validate_identity
from backend.app.models import FundContract, FundShare


def test_identity_accepts_official_short_name_without_structural_etf_token() -> None:
    fund = FundContract(
        canonical_name="新经济ETF银华",
        manager_name="银华基金",
        representative_code="159822",
        shares=[FundShare(share_code="159822")],
    )
    parsed = ParsedQuarterlyReport(
        fund_name="新经济",
        main_code="159822",
        manager_name="银华基金管理股份有限公司",
        period_end=date(2026, 6, 30),
        benchmark=None,
        share_codes=("159822",),
        target_fund_name=None,
        target_fund_code=None,
    )

    _validate_identity(fund, parsed)


def test_identity_still_rejects_a_different_specific_fund_name() -> None:
    fund = FundContract(
        canonical_name="新经济ETF银华",
        manager_name="银华基金",
        representative_code="159822",
        shares=[FundShare(share_code="159822")],
    )
    parsed = ParsedQuarterlyReport(
        fund_name="全球半导体ETF",
        main_code="159822",
        manager_name="银华基金管理股份有限公司",
        period_end=date(2026, 6, 30),
        benchmark=None,
        share_codes=("159822",),
        target_fund_name=None,
        target_fund_code=None,
    )

    with pytest.raises(ReportParseError, match="do not match"):
        _validate_identity(fund, parsed)


def test_security_table_classification_tolerates_interleaved_wide_headers() -> None:
    table = [
        ["序", "公司名称", "证券", "国家", "公允价值", "数量(股)", "净值比例"],
        ["号", "(英文)", "代码", "（地区）", "（人民币元）", "", "(%)"],
    ]

    assert _classify_table(table) == "SECURITY"


def test_security_table_classification_reads_vertically_split_headers() -> None:
    table = [
        ["序", "公司名称(英文)", "公", "证", "所", "所", "数量(股)", "公允价值", "占基金"],
        ["号", "", "司", "券", "在", "属", "", "（人民币元）", "资产净值"],
        ["", "", "名", "代", "证", "国", "", "", "比例(%)"],
        ["", "", "称", "码", "券市场", "家（地区）", "", "", ""],
        [
            "1",
            "MICRON TECHNOLOGY INC",
            "美光科技",
            "MU US",
            "美国证券交易所",
            "美国",
            "31,700",
            "249,217,594.22",
            "10.64",
        ],
    ]

    assert _classify_table(table) == "SECURITY"


def test_security_rank_tolerates_wrapped_two_digit_value() -> None:
    parsed = ParsedQuarterlyReport(
        fund_name="测试基金",
        main_code="160644",
        manager_name="测试基金管理有限公司",
        period_end=date(2026, 6, 30),
        benchmark=None,
        share_codes=("160644",),
        target_fund_name=None,
        target_fund_code=None,
    )

    _append_security(
        parsed,
        [
            "1\n0",
            "ADVANCED MICRO DEVICES",
            "-",
            "AMD US",
            "美国证券交易所",
            "美国",
            "20,920",
            "82,770,396.71",
            "3.53",
        ],
        11,
    )

    assert len(parsed.securities) == 1
    assert parsed.securities[0].rank == 10
    assert parsed.securities[0].security_code_raw == "AMD US"


def test_explicit_empty_detection_joins_wrapped_heading_but_stays_local() -> None:
    page_text = (
        """
      5.4.1 报告期末按公允价值排序的前十名股票及存托凭
      证投资明细
      无。
      5.9 前十名基金投资明细
      1 Target ETF 90.00%
    """
        + ("已披露基金持仓" * 40)
        + "无。"
    )

    empty = _explicit_empty_sections([page_text])

    assert "SECURITY" in empty
    assert "FUND" not in empty


def test_gics_unclassified_note_becomes_a_deterministic_industry_row() -> None:
    parsed = ParsedQuarterlyReport(
        fund_name="测试联接基金",
        main_code="015299",
        manager_name="测试基金管理有限公司",
        period_end=date(2026, 6, 30),
        benchmark=None,
        share_codes=("015299",),
        target_fund_name=None,
        target_fund_code=None,
    )
    note = (
        "本报告期末本基金持有的部分股票尚无全球行业分类标准（GICS），"
        "公允价值合计为 9,968.00 元，占基金资产净值比例合计为 0.00%，"
        "因此上表未包含。"
    )

    _append_unclassified_industry_note(note, parsed)
    _append_unclassified_industry_note(note, parsed)

    assert len(parsed.industries) == 1
    row = parsed.industries[0]
    assert row.label_normalized == "UNCLASSIFIED"
    assert row.fair_value_cny == Decimal("9968.00")
    assert row.nav_pct == Decimal("0.00")
    assert row.source_section == "行业分类投资组合脚注"
