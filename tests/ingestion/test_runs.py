from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.ingestion.runs import record_issue, resolve_issues
from backend.app.models import FundContract


def test_successful_rerun_resolves_only_matching_open_issue(db_session: Session) -> None:
    fund = FundContract(
        canonical_name="测试基金",
        manager_name="测试基金",
        representative_code="000001",
    )
    db_session.add(fund)
    db_session.flush()
    stale = record_issue(
        db_session,
        fund_contract_id=fund.id,
        issue_code="REPORT_PARSE_FAILED",
        severity="ERROR",
        message="old failure",
        details={},
    )
    current = record_issue(
        db_session,
        fund_contract_id=fund.id,
        issue_code="EMPTY_WITHOUT_EXPLICIT_DISCLOSURE",
        severity="WARNING",
        message="current warning",
        details={},
    )

    resolved = resolve_issues(
        db_session,
        fund_contract_id=fund.id,
        issue_codes=("REPORT_PARSE_FAILED",),
    )

    assert resolved == 1
    assert stale.status == "RESOLVED"
    assert stale.resolved_at is not None
    assert current.status == "OPEN"
