"""Report discovery, immutable archival, deterministic parsing, and persistence."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.ingestion.archive import archive_bytes
from backend.app.ingestion.parser import (
    PARSER_VERSION,
    ParsedQuarterlyReport,
    ReportParseError,
    derive_metrics,
    parse_quarterly_pdf,
)
from backend.app.ingestion.providers.base import ReportCandidate, ReportProvider
from backend.app.ingestion.runs import finish_run, record_issue, resolve_issues, start_run
from backend.app.models import (
    FundContract,
    FundRelation,
    FundReport,
    FundShare,
    IngestionRun,
    ReportAssetAllocation,
    ReportCountryAllocation,
    ReportDerivedMetrics,
    ReportFundHolding,
    ReportIndustryAllocation,
    ReportSecurityHolding,
    SourceArtifact,
)

PARSER_QUALITY_ISSUE_CODES = (
    "NEGATIVE_PERCENTAGE",
    "TOP_HOLDINGS_EXCEED_EQUITY",
    "FUND_INVESTMENT_RECONCILIATION",
    "EMPTY_WITHOUT_EXPLICIT_DISCLOSURE",
)
STRUCTURAL_NAME_TOKENS = frozenset({"ETF", "股票", "混合", "联接"})


def quarter_period(year: int, quarter: int) -> tuple[date, date]:
    if quarter not in {1, 2, 3, 4}:
        raise ValueError("quarter must be in 1..4")
    month = (quarter - 1) * 3 + 1
    end_month = month + 2
    next_month = date(year + 1, 1, 1) if end_month == 12 else date(year, end_month + 1, 1)
    return date(year, month, 1), date.fromordinal(next_month.toordinal() - 1)


def _get_or_create_report(
    session: Session, fund: FundContract, year: int, quarter: int, provider_name: str
) -> FundReport:
    report = session.scalar(
        select(FundReport).where(
            FundReport.fund_contract_id == fund.id,
            FundReport.report_type == "QUARTERLY",
            FundReport.report_year == year,
            FundReport.report_quarter == quarter,
        )
    )
    period_start, period_end = quarter_period(year, quarter)
    if report is None:
        report = FundReport(
            fund_contract_id=fund.id,
            report_type="QUARTERLY",
            report_year=year,
            report_quarter=quarter,
            period_start=period_start,
            period_end=period_end,
            source_provider=provider_name,
            parse_status="unresolved",
        )
        session.add(report)
        session.flush()
    return report


def sync_reports(
    session: Session,
    provider: ReportProvider,
    raw_root: Path,
    *,
    year: int,
    quarter: int,
    representative_codes: set[str] | None = None,
) -> IngestionRun:
    run = start_run(
        session,
        "sync_reports",
        {"provider": provider.name, "version": provider.version, "year": year, "quarter": quarter},
    )
    funds = list(
        session.scalars(
            select(FundContract)
            .where(FundContract.is_user_selected.is_(True))
            .order_by(FundContract.representative_code)
        )
    )
    if representative_codes is not None:
        funds = [fund for fund in funds if fund.representative_code in representative_codes]
    written = failed = 0
    for fund in funds:
        report = _get_or_create_report(session, fund, year, quarter, provider.name)
        try:
            candidates = provider.discover(fund.representative_code, year, quarter)
            if not candidates:
                report.parse_status = "unresolved"
                report.parse_error = "No matching quarterly report was discovered by this provider."
                record_issue(
                    session,
                    ingestion_run_id=run.id,
                    fund_contract_id=fund.id,
                    fund_report_id=report.id,
                    issue_code="REPORT_NOT_DISCOVERED",
                    severity="WARNING",
                    message=f"No {year} Q{quarter} report found for {fund.representative_code}",
                    details={"provider": provider.name, "provider_version": provider.version},
                )
                failed += 1
                session.commit()
                continue
            candidate = _select_candidate(session, run, fund, report, candidates)
            previous_sha256 = report.sha256
            previous_parse_status = report.parse_status
            report.public_available_at = candidate.public_available_at
            report.source_provider = candidate.provider_name
            report.source_page_url = candidate.source_page_url
            report.document_url = candidate.document_url
            report.mime_type = candidate.mime_type or "application/pdf"
            payload = provider.download(candidate)
            artifact = archive_bytes(
                raw_root,
                Path("reports")
                / provider.name.lower()
                / f"{year}q{quarter}"
                / fund.representative_code,
                f"{fund.representative_code}-{year}q{quarter}",
                ".pdf",
                payload,
            )
            report.local_document_path = str(artifact.path.relative_to(raw_root.resolve()))
            report.sha256 = artifact.sha256
            if previous_sha256 != artifact.sha256 or previous_parse_status not in {
                "parsed",
                "valid_empty",
            }:
                report.parse_status = "downloaded"
                report.parse_error = None
            existing_artifact = session.scalar(
                select(SourceArtifact).where(
                    SourceArtifact.source_provider == candidate.provider_name,
                    SourceArtifact.sha256 == artifact.sha256,
                )
            )
            if existing_artifact is None:
                session.add(
                    SourceArtifact(
                        ingestion_run_id=run.id,
                        fund_contract_id=fund.id,
                        fund_report_id=report.id,
                        artifact_type="QUARTERLY_REPORT_PDF",
                        source_provider=candidate.provider_name,
                        source_url=candidate.document_url,
                        local_path=report.local_document_path,
                        mime_type=report.mime_type,
                        sha256=artifact.sha256,
                        byte_size=artifact.byte_size,
                        fetched_at=artifact.fetched_at,
                        metadata_json={
                            "provider_version": candidate.provider_version,
                            "title": candidate.title,
                            "source_page_url": candidate.source_page_url,
                        },
                    )
                )
            resolved_codes = ["REPORT_NOT_DISCOVERED", "REPORT_SYNC_FAILED"]
            if len(candidates) == 1:
                resolved_codes.append("MULTIPLE_REPORT_CANDIDATES")
            resolve_issues(
                session,
                fund_contract_id=fund.id,
                fund_report_id=report.id,
                issue_codes=tuple(resolved_codes),
            )
            written += 1
        except Exception as error:  # provider failures are persisted per fund before continuing
            report.parse_status = "failed_with_reason"
            report.parse_error = str(error)
            record_issue(
                session,
                ingestion_run_id=run.id,
                fund_contract_id=fund.id,
                fund_report_id=report.id,
                issue_code="REPORT_SYNC_FAILED",
                severity="ERROR",
                message=f"Report sync failed for {fund.representative_code}: {error}",
                details={"provider": provider.name, "exception_type": type(error).__name__},
            )
            failed += 1
        session.commit()
    status = "succeeded" if failed == 0 else "partial"
    finish_run(run, status=status, seen=len(funds), written=written, failed=failed)
    session.commit()
    return run


def _select_candidate(
    session: Session,
    run: IngestionRun,
    fund: FundContract,
    report: FundReport,
    candidates: list[ReportCandidate],
) -> ReportCandidate:
    ordered = sorted(
        candidates,
        key=lambda item: (
            "提示性公告" not in item.title and "旗下" not in item.title,
            item.public_available_at.isoformat() if item.public_available_at else "",
            item.document_url,
        ),
        reverse=True,
    )
    if len(ordered) > 1:
        record_issue(
            session,
            ingestion_run_id=run.id,
            fund_contract_id=fund.id,
            fund_report_id=report.id,
            issue_code="MULTIPLE_REPORT_CANDIDATES",
            severity="WARNING",
            message=(
                "Multiple matching report documents found; selected the latest disclosed candidate."
            ),
            details={"candidate_urls": [item.document_url for item in ordered]},
        )
    return ordered[0]


def parse_reports(
    session: Session,
    raw_root: Path,
    *,
    year: int,
    quarter: int,
    representative_codes: set[str] | None = None,
) -> IngestionRun:
    run = start_run(session, "parse_reports", {"year": year, "quarter": quarter})
    run_id = run.id
    session.commit()
    statement = (
        select(FundReport)
        .join(FundContract)
        .where(
            FundContract.is_user_selected.is_(True),
            FundReport.report_type == "QUARTERLY",
            FundReport.report_year == year,
            FundReport.report_quarter == quarter,
        )
        .order_by(FundContract.representative_code)
    )
    reports = list(session.scalars(statement))
    if representative_codes is not None:
        reports = [
            report
            for report in reports
            if report.fund_contract.representative_code in representative_codes
        ]
    written = failed = 0
    for report in reports:
        fund = report.fund_contract
        report_id = report.id
        fund_id = fund.id
        fund_code = fund.representative_code
        if not report.local_document_path:
            if report.parse_status not in {"unresolved", "failed_with_reason"}:
                report.parse_status = "unresolved"
                report.parse_error = "Report has no local source document."
            record_issue(
                session,
                ingestion_run_id=run_id,
                fund_contract_id=fund_id,
                fund_report_id=report_id,
                issue_code="REPORT_SOURCE_MISSING",
                severity="ERROR",
                message=f"Report has no archived source document for {fund_code}",
                details={"year": year, "quarter": quarter},
            )
            failed += 1
            session.commit()
            continue
        try:
            path = (raw_root / report.local_document_path).resolve()
            path.relative_to(raw_root.resolve())
            parsed = parse_quarterly_pdf(path.read_bytes())
            _validate_identity(fund, parsed)
            _replace_report_rows(session, report, parsed)
            report.parser_version = PARSER_VERSION
            report.parse_status = "parsed"
            report.parse_confidence = parsed.parse_confidence
            report.parse_error = None
            resolve_issues(
                session,
                fund_contract_id=fund.id,
                fund_report_id=report.id,
                issue_codes=(
                    "REPORT_PARSE_FAILED",
                    "REPORT_SOURCE_MISSING",
                    *PARSER_QUALITY_ISSUE_CODES,
                ),
            )
            for issue in parsed.quality_issues:
                record_issue(
                    session,
                    ingestion_run_id=run.id,
                    fund_contract_id=fund.id,
                    fund_report_id=report.id,
                    issue_code=str(issue["code"]),
                    severity="WARNING",
                    message=f"Report quality check: {issue['code']}",
                    details=issue,
                )
            written += 1
        except Exception as error:
            session.rollback()
            persisted_report = session.get(FundReport, report_id)
            if persisted_report is not None:
                persisted_report.parse_status = "failed_with_reason"
                persisted_report.parse_error = str(error)
            record_issue(
                session,
                ingestion_run_id=run_id,
                fund_contract_id=fund_id,
                fund_report_id=report_id,
                issue_code="REPORT_PARSE_FAILED",
                severity="ERROR",
                message=f"Report parse failed for {fund_code}: {error}",
                details={"parser_version": PARSER_VERSION, "exception_type": type(error).__name__},
            )
            failed += 1
        session.commit()
    persisted_run = session.get(IngestionRun, run_id)
    if persisted_run is None:
        raise RuntimeError(f"Ingestion run {run_id} disappeared during report parsing")
    finish_run(
        persisted_run,
        status="succeeded" if failed == 0 else "partial",
        seen=len(reports),
        written=written,
        failed=failed,
    )
    session.commit()
    return persisted_run


def _validate_identity(fund: FundContract, parsed: ParsedQuarterlyReport) -> None:
    known_codes = {fund.representative_code, *(share.share_code for share in fund.shares)}
    if parsed.main_code not in known_codes:
        raise ReportParseError(
            f"Report main code {parsed.main_code} does not match contract codes "
            f"{sorted(known_codes)}"
        )
    if _manager_key(fund.manager_name) != _manager_key(parsed.manager_name):
        raise ReportParseError(
            f"Report manager {parsed.manager_name!r} does not match {fund.manager_name!r}"
        )
    expected_tokens = _name_tokens(fund.canonical_name)
    actual_tokens = _name_tokens(parsed.fund_name)
    required_tokens = expected_tokens - STRUCTURAL_NAME_TOKENS
    if required_tokens and not required_tokens.issubset(actual_tokens):
        raise ReportParseError(
            f"Report name tokens {sorted(actual_tokens)} do not match {sorted(required_tokens)}"
        )


def _manager_key(value: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9\u3400-\u9fff]", "", value).upper()
    for suffix in (
        "基金管理中国有限公司",
        "基金管理有限责任公司",
        "基金管理股份有限公司",
        "基金管理有限公司",
        "基金股份有限公司",
        "基金有限公司",
        "有限责任公司",
        "股份有限公司",
        "有限公司",
        "基金管理",
        "基金",
    ):
        if compact.endswith(suffix):
            compact = compact[: -len(suffix)]
            break
    return compact


def _name_tokens(value: str) -> set[str]:
    compact = re.sub(r"[^A-Za-z0-9\u3400-\u9fff]", "", value).upper()
    compact = compact.replace("纳指", "纳斯达克")
    replacements = {
        "交易型开放式指数证券投资基金": "ETF",
        "交易型开放式": "ETF",
        "证券投资基金": "",
        "发起式": "",
        "基金": "",
        "QDII": "",
        "LOF": "",
    }
    for old, new in replacements.items():
        compact = compact.replace(old, new)
    keywords = (
        "纳斯达克",
        "100",
        "半导体",
        "芯片",
        "全球",
        "中韩",
        "联接",
        "ETF",
        "股票",
        "混合",
        "新经济",
    )
    return {keyword for keyword in keywords if keyword in compact}


def _replace_report_rows(
    session: Session, report: FundReport, parsed: ParsedQuarterlyReport
) -> None:
    for model in (
        ReportAssetAllocation,
        ReportCountryAllocation,
        ReportIndustryAllocation,
        ReportSecurityHolding,
        ReportFundHolding,
        ReportDerivedMetrics,
    ):
        session.execute(delete(model).where(model.fund_report_id == report.id))
    session.execute(
        delete(FundRelation).where(
            FundRelation.report_id == report.id,
            FundRelation.relation_type.in_(["FEEDER_TO_TARGET_ETF", "REPORT_FUND_HOLDING"]),
        )
    )
    for asset in parsed.assets:
        session.add(
            ReportAssetAllocation(
                fund_report_id=report.id,
                asset_name_raw=asset.label_raw,
                asset_name_normalized=asset.label_normalized,
                fair_value_cny=asset.fair_value_cny,
                nav_pct=asset.nav_pct,
                rank=asset.rank,
                source_section=asset.source_section,
                raw_row=asset.raw_row,
                parse_confidence=asset.confidence,
                exposure_basis="DIRECT",
            )
        )
    for country in parsed.countries:
        session.add(
            ReportCountryAllocation(
                fund_report_id=report.id,
                country_name_raw=country.label_raw,
                country_name_normalized=country.label_normalized,
                fair_value_cny=country.fair_value_cny,
                nav_pct=country.nav_pct,
                rank=country.rank,
                source_section=country.source_section,
                raw_row=country.raw_row,
                parse_confidence=country.confidence,
                exposure_basis="DIRECT",
            )
        )
    for industry in parsed.industries:
        session.add(
            ReportIndustryAllocation(
                fund_report_id=report.id,
                industry_name_raw=industry.label_raw,
                industry_name_normalized=industry.label_normalized,
                fair_value_cny=industry.fair_value_cny,
                nav_pct=industry.nav_pct,
                rank=industry.rank,
                source_section=industry.source_section,
                raw_row=industry.raw_row,
                parse_confidence=industry.confidence,
                exposure_basis="DIRECT",
            )
        )
    for security in parsed.securities:
        session.add(
            ReportSecurityHolding(
                fund_report_id=report.id,
                security_code_raw=security.security_code_raw,
                security_name_raw=security.security_name_raw,
                security_name_normalized=security.security_name_normalized,
                security_name_zh=security.security_name_zh,
                security_name_en=security.security_name_en,
                exchange_raw=security.exchange_raw,
                market_normalized=security.market_normalized,
                country_normalized=security.country_normalized,
                currency=security.currency,
                quantity=security.quantity,
                fair_value_cny=security.fair_value_cny,
                nav_pct=security.nav_pct,
                rank=security.rank,
                security_type=security.security_type,
                source_section=security.source_section,
                raw_row=security.raw_row,
                parse_confidence=security.confidence,
                exposure_basis="DIRECT",
            )
        )
    target = None
    if parsed.target_fund_code:
        target = _resolve_or_create_dependency(
            session, parsed.target_fund_code, parsed.target_fund_name or parsed.target_fund_code
        )
    for fund_holding in parsed.funds:
        resolved = target if fund_holding.fund_code_raw == parsed.target_fund_code else None
        if resolved is None and fund_holding.fund_code_raw:
            resolved = _resolve_contract(session, fund_holding.fund_code_raw)
        holding = ReportFundHolding(
            fund_report_id=report.id,
            resolved_fund_contract_id=resolved.id if resolved else None,
            fund_code_raw=fund_holding.fund_code_raw,
            fund_name_raw=fund_holding.fund_name_raw,
            fund_name_normalized=fund_holding.fund_name_normalized,
            currency=fund_holding.currency,
            is_unresolved=resolved is None,
            fair_value_cny=fund_holding.fair_value_cny,
            nav_pct=fund_holding.nav_pct,
            rank=fund_holding.rank,
            source_section=fund_holding.source_section,
            raw_row=fund_holding.raw_row,
            parse_confidence=fund_holding.confidence,
            exposure_basis="DIRECT",
        )
        session.add(holding)
        relation_type = (
            "FEEDER_TO_TARGET_ETF"
            if target is not None and resolved is not None and resolved.id == target.id
            else "REPORT_FUND_HOLDING"
        )
        session.add(
            FundRelation(
                source_fund_contract_id=report.fund_contract_id,
                target_fund_contract_id=resolved.id if resolved else None,
                external_target_name=None if resolved else fund_holding.fund_name_raw,
                external_target_code=None if resolved else fund_holding.fund_code_raw,
                relation_type=relation_type,
                effective_from=report.period_start,
                effective_to=report.period_end,
                report_id=report.id,
                weight_nav_pct=fund_holding.nav_pct,
                source_text=fund_holding.fund_name_raw,
                confidence=fund_holding.confidence,
            )
        )
    metrics = derive_metrics(parsed)
    report.fund_contract.tech_scope = str(metrics["tech_scope"])
    session.add(ReportDerivedMetrics(fund_report_id=report.id, **metrics))
    session.flush()


def _resolve_contract(session: Session, code: str) -> FundContract | None:
    contract = session.scalar(select(FundContract).where(FundContract.representative_code == code))
    if contract is not None:
        return contract
    share = session.scalar(select(FundShare).where(FundShare.share_code == code))
    return share.fund_contract if share is not None else None


def _resolve_or_create_dependency(session: Session, code: str, name: str) -> FundContract:
    contract = _resolve_contract(session, code)
    if contract is not None:
        return contract
    contract = FundContract(
        canonical_name=name,
        manager_name="UNRESOLVED_FROM_REPORT",
        representative_code=code,
        strategy_type=None,
        original_category=None,
        wrapper_type="ETF",
        tech_scope="UNKNOWN",
        is_user_selected=False,
        is_dependency=True,
    )
    session.add(contract)
    session.flush()
    session.add(
        FundShare(
            fund_contract_id=contract.id,
            share_code=code,
            currency="CNY",
            is_exchange_traded=code.startswith(("15", "16", "50", "51")),
            exchange=(
                "SZSE"
                if code.startswith(("15", "16"))
                else "SSE"
                if code.startswith(("50", "51"))
                else None
            ),
        )
    )
    session.flush()
    return contract
