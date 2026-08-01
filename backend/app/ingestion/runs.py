"""Audit helpers for ingestion runs and data-quality issues."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import DataQualityIssue, IngestionRun


def start_run(session: Session, job_type: str, parameters: dict[str, Any]) -> IngestionRun:
    run = IngestionRun(job_type=job_type, status="running", parameters=parameters)
    session.add(run)
    session.flush()
    return run


def finish_run(
    run: IngestionRun,
    *,
    status: str,
    seen: int,
    written: int,
    failed: int,
    error: str | None = None,
) -> None:
    run.status = status
    run.finished_at = datetime.now(UTC)
    run.records_seen = seen
    run.records_written = written
    run.records_failed = failed
    run.error_message = error


def record_issue(
    session: Session,
    *,
    issue_code: str,
    severity: str,
    message: str,
    details: dict[str, Any],
    ingestion_run_id: int | None = None,
    fund_contract_id: int | None = None,
    fund_report_id: int | None = None,
    fund_share_id: int | None = None,
) -> DataQualityIssue:
    """Create one open issue per code/context; reruns update evidence instead of duplicating it."""

    filters = [
        DataQualityIssue.issue_code == issue_code,
        DataQualityIssue.status == "OPEN",
        DataQualityIssue.fund_contract_id == fund_contract_id,
        DataQualityIssue.fund_report_id == fund_report_id,
        DataQualityIssue.fund_share_id == fund_share_id,
    ]
    issue = session.scalar(select(DataQualityIssue).where(*filters).order_by(DataQualityIssue.id))
    if issue is None:
        issue = DataQualityIssue(
            ingestion_run_id=ingestion_run_id,
            fund_contract_id=fund_contract_id,
            fund_report_id=fund_report_id,
            fund_share_id=fund_share_id,
            issue_code=issue_code,
            severity=severity,
            message=message,
            details=details,
        )
        session.add(issue)
    else:
        issue.ingestion_run_id = ingestion_run_id or issue.ingestion_run_id
        issue.severity = severity
        issue.message = message
        issue.details = details
        issue.detected_at = datetime.now(UTC)
    session.flush()
    return issue


def resolve_issues(
    session: Session,
    *,
    issue_codes: tuple[str, ...],
    fund_contract_id: int | None = None,
    fund_report_id: int | None = None,
    fund_share_id: int | None = None,
) -> int:
    """Close matching open issues after a later successful, context-equivalent run."""

    issues = list(
        session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.status == "OPEN",
                DataQualityIssue.issue_code.in_(issue_codes),
                DataQualityIssue.fund_contract_id == fund_contract_id,
                DataQualityIssue.fund_report_id == fund_report_id,
                DataQualityIssue.fund_share_id == fund_share_id,
            )
        )
    )
    resolved_at = datetime.now(UTC)
    for issue in issues:
        issue.status = "RESOLVED"
        issue.resolved_at = resolved_at
    session.flush()
    return len(issues)
