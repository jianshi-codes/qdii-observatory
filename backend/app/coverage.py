"""Deterministic quarterly coverage report generation."""

from __future__ import annotations

import csv
import io
import os
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

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

COVERAGE_COLUMNS = (
    "representative_code",
    "fund_name",
    "manager",
    "report_status",
    "report_found",
    "downloaded",
    "parsed",
    "parse_confidence",
    "wrapper_type",
    "target_fund_code",
    "direct_country_available",
    "direct_industry_available",
    "stock_holding_count",
    "fund_holding_count",
    "lookthrough_status",
    "source_url",
    "failure_reason",
)


class CoverageError(RuntimeError):
    """Raised before writing when the selected universe is incomplete."""


@dataclass(frozen=True, slots=True)
class CoverageRow:
    representative_code: str
    fund_name: str
    manager: str
    report_status: str
    report_found: bool
    downloaded: bool
    parsed: bool
    parse_confidence: Decimal | None
    wrapper_type: str
    target_fund_code: str
    direct_country_available: bool
    direct_industry_available: bool
    stock_holding_count: int
    fund_holding_count: int
    lookthrough_status: str
    source_url: str
    failure_reason: str


@dataclass(frozen=True, slots=True)
class CoverageResult:
    csv_path: Path
    markdown_path: Path
    rows: tuple[CoverageRow, ...]


def build_coverage_rows(
    session: Session,
    *,
    year: int,
    quarter: int,
    expected_count: int | None = None,
) -> tuple[CoverageRow, ...]:
    """Return one explicit, representative-code-sorted status row per selected fund."""

    funds = list(
        session.scalars(
            select(FundContract)
            .where(FundContract.is_user_selected.is_(True))
            .order_by(FundContract.representative_code)
        )
    )
    if not funds:
        raise CoverageError("Coverage requires at least one enabled fund contract")
    if expected_count is not None and len(funds) != expected_count:
        codes = [fund.representative_code for fund in funds]
        raise CoverageError(
            "Coverage expected "
            f"{expected_count} user-selected fund contracts, found {len(funds)}; "
            f"codes={codes}"
        )

    reports = list(
        session.scalars(
            select(FundReport).where(
                FundReport.fund_contract_id.in_([fund.id for fund in funds]),
                FundReport.report_type == "QUARTERLY",
                FundReport.report_year == year,
                FundReport.report_quarter == quarter,
            )
        )
    )
    report_by_fund = {report.fund_contract_id: report for report in reports}
    report_ids = [report.id for report in reports]

    direct_country_counts = _row_counts(
        session, ReportCountryAllocation, report_ids, basis="DIRECT"
    )
    direct_industry_counts = _row_counts(
        session, ReportIndustryAllocation, report_ids, basis="DIRECT"
    )
    stock_counts = _row_counts(session, ReportSecurityHolding, report_ids, basis="DIRECT")
    fund_counts = _row_counts(session, ReportFundHolding, report_ids, basis="DIRECT")
    lookthrough_country_counts = _row_counts(
        session, ReportCountryAllocation, report_ids, basis="LOOKTHROUGH"
    )
    lookthrough_industry_counts = _row_counts(
        session, ReportIndustryAllocation, report_ids, basis="LOOKTHROUGH"
    )
    metrics_by_report = {
        item.fund_report_id: item
        for item in session.scalars(
            select(ReportDerivedMetrics).where(ReportDerivedMetrics.fund_report_id.in_(report_ids))
        )
    }
    target_codes = _target_codes(session, report_ids)

    rows = []
    for fund in funds:
        report = report_by_fund.get(fund.id)
        status = _report_status(report)
        report_id = report.id if report else 0
        fund_holding_count = fund_counts.get(report_id, 0)
        metrics = metrics_by_report.get(report_id)
        rows.append(
            CoverageRow(
                representative_code=fund.representative_code,
                fund_name=fund.canonical_name,
                manager=fund.manager_name,
                report_status=status,
                report_found=bool(report and report.document_url),
                downloaded=bool(report and report.local_document_path and report.sha256),
                parsed=status in {"parsed", "valid_empty"},
                parse_confidence=report.parse_confidence if report else None,
                wrapper_type=fund.wrapper_type or "UNKNOWN",
                target_fund_code=";".join(target_codes.get(report_id, ())),
                direct_country_available=direct_country_counts.get(report_id, 0) > 0,
                direct_industry_available=direct_industry_counts.get(report_id, 0) > 0,
                stock_holding_count=stock_counts.get(report_id, 0),
                fund_holding_count=fund_holding_count,
                lookthrough_status=_lookthrough_status(
                    status=status,
                    fund_holding_count=fund_holding_count,
                    lookthrough_row_count=(
                        lookthrough_country_counts.get(report_id, 0)
                        + lookthrough_industry_counts.get(report_id, 0)
                    ),
                    metrics=metrics,
                ),
                source_url=(
                    (report.source_page_url or report.document_url or "") if report else ""
                ),
                failure_reason=_failure_reason(report, status, year, quarter),
            )
        )
    return tuple(rows)


def generate_coverage(
    session: Session,
    output_dir: Path,
    *,
    year: int,
    quarter: int,
    expected_count: int | None = None,
) -> CoverageResult:
    rows = build_coverage_rows(
        session,
        year=year,
        quarter=quarter,
        expected_count=expected_count,
    )
    stem = f"{year}q{quarter}-coverage"
    csv_path = output_dir / f"{stem}.csv"
    markdown_path = output_dir / f"{stem}.md"
    _atomic_write(csv_path, render_coverage_csv(rows))
    _atomic_write(markdown_path, render_coverage_markdown(rows, year, quarter))
    return CoverageResult(csv_path=csv_path, markdown_path=markdown_path, rows=rows)


def render_coverage_csv(rows: tuple[CoverageRow, ...]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=COVERAGE_COLUMNS,
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for row in rows:
        values = asdict(row)
        writer.writerow({key: _csv_value(values[key]) for key in COVERAGE_COLUMNS})
    return stream.getvalue()


def render_coverage_markdown(rows: tuple[CoverageRow, ...], year: int, quarter: int) -> str:
    status_counts = Counter(row.report_status for row in rows)
    lines = [
        f"# QDII {year} Q{quarter} 覆盖报告",
        "",
        f"- 用户选择基金：{len(rows)}",
        f"- 已发现报告：{sum(row.report_found for row in rows)}",
        f"- 已下载：{sum(row.downloaded for row in rows)}",
        f"- 已解析或有效空表：{sum(row.parsed for row in rows)}",
        "",
        "## 状态汇总",
        "",
        "| 状态 | 数量 |",
        "| --- | ---: |",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"| {_markdown_cell(status)} | {count} |")
    lines.extend(
        [
            "",
            "## 逐基金状态",
            "",
            "| 代表代码 | 基金名称 | 管理人 | 报告状态 | 解析置信度 | 股票持仓 | "
            "基金持仓 | 穿透状态 | 失败原因 |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in rows:
        confidence = "" if row.parse_confidence is None else str(row.parse_confidence)
        lines.append(
            "| "
            + " | ".join(
                _markdown_cell(value)
                for value in (
                    row.representative_code,
                    row.fund_name,
                    row.manager,
                    row.report_status,
                    confidence,
                    str(row.stock_holding_count),
                    str(row.fund_holding_count),
                    row.lookthrough_status,
                    row.failure_reason,
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _row_counts(
    session: Session,
    model: type[
        ReportCountryAllocation
        | ReportIndustryAllocation
        | ReportSecurityHolding
        | ReportFundHolding
    ],
    report_ids: list[int],
    *,
    basis: str,
) -> dict[int, int]:
    if not report_ids:
        return {}
    rows = session.execute(
        select(model.fund_report_id, func.count(model.id))
        .where(
            model.fund_report_id.in_(report_ids),
            model.exposure_basis == basis,
        )
        .group_by(model.fund_report_id)
    )
    return {report_id: count for report_id, count in rows}


def _target_codes(session: Session, report_ids: list[int]) -> dict[int, tuple[str, ...]]:
    if not report_ids:
        return {}
    target = aliased(FundContract)
    rows = session.execute(
        select(
            FundRelation.report_id,
            target.representative_code,
            FundRelation.external_target_code,
        )
        .outerjoin(target, FundRelation.target_fund_contract_id == target.id)
        .where(
            FundRelation.report_id.in_(report_ids),
            FundRelation.relation_type == "FEEDER_TO_TARGET_ETF",
        )
    )
    values: dict[int, set[str]] = {}
    for report_id, internal_code, external_code in rows:
        if report_id is None:
            continue
        code = internal_code or external_code
        if code:
            values.setdefault(report_id, set()).add(code)
    return {report_id: tuple(sorted(codes)) for report_id, codes in values.items()}


def _report_status(report: FundReport | None) -> str:
    if report is None:
        return "unresolved"
    status = (report.parse_status or "").strip().lower()
    aliases = {"failed": "failed_with_reason", "valid-empty": "valid_empty"}
    return aliases.get(status, status or "unresolved")


def _failure_reason(report: FundReport | None, status: str, year: int, quarter: int) -> str:
    if report is None:
        return f"No fund_report row for {year} Q{quarter}."
    if status in {"parsed", "valid_empty"}:
        return ""
    if report.parse_error:
        return report.parse_error.strip()
    if status == "downloaded":
        return "Report downloaded but not parsed."
    return f"Report status is {status}."


def _lookthrough_status(
    *,
    status: str,
    fund_holding_count: int,
    lookthrough_row_count: int,
    metrics: ReportDerivedMetrics | None,
) -> str:
    if status not in {"parsed", "valid_empty"}:
        return "not_available"
    if metrics and metrics.circular_relation_detected:
        return "circular_relation_detected"
    if fund_holding_count == 0:
        return "direct_only"
    if metrics is None:
        return "not_calculated"
    unresolved = metrics.unresolved_fund_weight_pct or Decimal("0")
    coverage = metrics.lookthrough_coverage_pct or Decimal("0")
    if unresolved > 0:
        return "partial" if coverage > 0 else "unresolved"
    if lookthrough_row_count > 0 and coverage > 0:
        return "resolved"
    return "unresolved"


def _csv_value(value: object) -> object:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return str(value)
    if value is None:
        return ""
    return value


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
