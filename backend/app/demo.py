"""Load an explicitly synthetic, offline demo dataset."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import (
    DailyFundNav,
    FundContract,
    FundReport,
    FundShare,
    ReportCountryAllocation,
    ReportDerivedMetrics,
    ReportIndustryAllocation,
    ReportSecurityHolding,
)


def load_synthetic_demo(session: Session, path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "Entirely synthetic" not in str(payload.get("notice")):
        raise ValueError("demo file must explicitly declare that it is entirely synthetic")
    source = payload["report"]
    fund = session.scalar(
        select(FundContract).where(FundContract.representative_code == source["fund_code"])
    )
    if fund is None:
        raise ValueError("import examples/universe.sample.csv before loading the demo")
    share = session.scalar(
        select(FundShare).where(FundShare.share_code == fund.representative_code)
    )
    assert share is not None
    report = session.scalar(
        select(FundReport).where(
            FundReport.fund_contract_id == fund.id,
            FundReport.report_year == int(source["report_year"]),
            FundReport.report_quarter == int(source["report_quarter"]),
        )
    )
    if report is None:
        report = FundReport(
            fund_contract_id=fund.id,
            report_type="QUARTERLY",
            report_year=int(source["report_year"]),
            report_quarter=int(source["report_quarter"]),
            period_start=date.fromisoformat(source["period_start"]),
            period_end=date.fromisoformat(source["period_end"]),
            public_available_at=datetime.fromisoformat(source["public_available_at"]),
            source_provider="SYNTHETIC_DEMO",
            source_page_url=None,
            document_url=None,
            local_document_path=None,
            mime_type="application/json",
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            parser_version="synthetic-v1",
            parse_status="PARSED",
            parse_confidence=Decimal("1"),
        )
        session.add(report)
        session.flush()
        for rank, (country, weight) in enumerate(source["countries"].items(), start=1):
            session.add(
                ReportCountryAllocation(
                    fund_report_id=report.id,
                    country_name_raw=country,
                    country_name_normalized=country,
                    exposure_basis="DIRECT",
                    nav_pct=Decimal(weight),
                    rank=rank,
                    source_section="synthetic",
                    raw_row={},
                    parse_confidence=Decimal("1"),
                )
            )
        for rank, (industry, weight) in enumerate(source["industries"].items(), start=1):
            session.add(
                ReportIndustryAllocation(
                    fund_report_id=report.id,
                    industry_name_raw=industry,
                    industry_name_normalized=industry,
                    exposure_basis="DIRECT",
                    nav_pct=Decimal(weight),
                    rank=rank,
                    source_section="synthetic",
                    raw_row={},
                    parse_confidence=Decimal("1"),
                )
            )
        for rank, holding in enumerate(source["top_holdings"], start=1):
            session.add(
                ReportSecurityHolding(
                    fund_report_id=report.id,
                    security_code_raw=holding["code"],
                    security_name_raw=holding["name"],
                    security_name_normalized=holding["name"],
                    security_type="EQUITY",
                    exposure_basis="DIRECT",
                    nav_pct=Decimal(holding["weight"]),
                    rank=rank,
                    source_section="synthetic",
                    raw_row={},
                    parse_confidence=Decimal("1"),
                )
            )
        session.add(
            ReportDerivedMetrics(
                fund_report_id=report.id,
                tech_scope=fund.tech_scope,
                disclosed_top10_pct=sum(
                    (Decimal(item["weight"]) for item in source["top_holdings"]), Decimal("0")
                ),
                undisclosed_equity_pct=Decimal(source["undisclosed_equity_pct"]),
                lookthrough_coverage_pct=Decimal("100"),
                unresolved_fund_weight_pct=Decimal("0"),
                max_lookthrough_depth=0,
                data_as_of=report.period_end,
            )
        )
    nav_written = 0
    for item in payload["nav"]:
        nav_date = date.fromisoformat(item["date"])
        existing = session.scalar(
            select(DailyFundNav).where(
                DailyFundNav.fund_share_id == share.id,
                DailyFundNav.nav_date == nav_date,
                DailyFundNav.source_provider == "SYNTHETIC_DEMO",
            )
        )
        if existing is None:
            session.add(
                DailyFundNav(
                    fund_share_id=share.id,
                    nav_date=nav_date,
                    unit_nav=Decimal(item["unit_nav"]),
                    published_daily_return_pct=Decimal(item["return_pct"]),
                    calculated_daily_return_pct=None,
                    source_provider="SYNTHETIC_DEMO",
                    source_published_at=None,
                    raw_payload_hash=hashlib.sha256(
                        json.dumps(item, sort_keys=True).encode()
                    ).hexdigest(),
                )
            )
            nav_written += 1
    session.commit()
    return {"reports": 1, "nav_rows_written": nav_written}
