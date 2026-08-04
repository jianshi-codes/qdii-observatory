"""PostgreSQL-backed queue for the small set of user-triggered data operations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.data_operations import (
    DataOperationResult,
    parse_reports_data,
    sync_daily_data,
    sync_reports_data,
    sync_sales_limits_data,
)
from backend.app.models import DataOperation


class OperationInProgressError(RuntimeError):
    """A queued or running durable data operation already owns the active slot."""


STAGE_TOTALS = {
    "prepare": 3,
    "sync-daily": 1,
    "sync-sales-limits": 1,
    "sync-reports": 1,
    "parse-reports": 1,
}


def enqueue_operation(
    session: Session,
    *,
    operation: str,
    fund_codes: tuple[str, ...],
    lookback_days: int,
    report_year: int,
    report_quarter: int,
) -> DataOperation:
    item = DataOperation(
        operation=operation,
        status="queued",
        active_slot=1,
        fund_codes=list(fund_codes),
        lookback_days=lookback_days,
        report_year=report_year,
        report_quarter=report_quarter,
        stage_completed=0,
        stage_total=STAGE_TOTALS[operation],
        run_ids=[],
    )
    session.add(item)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        active = session.scalar(
            select(DataOperation)
            .where(DataOperation.active_slot == 1)
            .order_by(DataOperation.id.desc())
        )
        if active is not None:
            raise OperationInProgressError(
                f"data operation {active.id} ({active.operation}) is {active.status}"
            ) from error
        raise
    session.refresh(item)
    return item


def latest_operation(session: Session) -> DataOperation | None:
    return session.scalar(select(DataOperation).order_by(DataOperation.id.desc()).limit(1))


def recover_interrupted_operations(session: Session) -> int:
    interrupted = list(
        session.scalars(select(DataOperation).where(DataOperation.status == "running"))
    )
    now = datetime.now(UTC)
    for item in interrupted:
        item.status = "failed"
        item.active_slot = None
        item.finished_at = now
        item.error_message = "worker restarted before this operation completed; retry is safe"
    session.commit()
    return len(interrupted)


def claim_next_operation(session: Session) -> int | None:
    item = session.scalar(
        select(DataOperation)
        .where(DataOperation.status == "queued")
        .order_by(DataOperation.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if item is None:
        session.rollback()
        return None
    item.status = "running"
    item.started_at = datetime.now(UTC)
    item.current_stage = _stages(item.operation)[0][0]
    session.commit()
    return item.id


def execute_operation(session: Session, operation_id: int, raw_root: Path) -> DataOperation:
    item = session.get(DataOperation, operation_id)
    if item is None or item.status != "running":
        raise RuntimeError(f"data operation {operation_id} is not running")
    results: list[DataOperationResult] = []
    try:
        for index, (stage_name, execute) in enumerate(_stages(item.operation), start=1):
            current = _required_operation(session, operation_id)
            current.current_stage = stage_name
            session.commit()
            result = execute(session, raw_root, current)
            results.append(result)
            current = _required_operation(session, operation_id)
            current.stage_completed = index
            current.run_ids = [*current.run_ids, *(run.id for run in result.runs)]
            current.records_written += sum(run.records_written for run in result.runs)
            current.records_failed += sum(run.records_failed for run in result.runs)
            current.recurring_orders_created += result.recurring_orders_created
            current.recurring_orders_settled += result.recurring_orders_settled
            current.recurring_executions_written += result.recurring_executions_written
            current.recurring_positions_updated += result.recurring_positions_updated
            if result.recurring_latest_nav_date is not None:
                current.recurring_latest_nav_date = result.recurring_latest_nav_date
            session.commit()
    except Exception as error:
        session.rollback()
        failed = _required_operation(session, operation_id)
        failed.status = "failed"
        failed.active_slot = None
        failed.current_stage = None
        failed.finished_at = datetime.now(UTC)
        failed.error_message = f"{type(error).__name__}: {error}"
        session.commit()
        return failed

    completed = _required_operation(session, operation_id)
    completed.status = _combined_result_status(results)
    completed.active_slot = None
    completed.current_stage = None
    completed.finished_at = datetime.now(UTC)
    session.commit()
    return completed


StageExecutor = Callable[[Session, Path, DataOperation], DataOperationResult]


def _stages(operation: str) -> tuple[tuple[str, StageExecutor], ...]:
    stages: dict[str, tuple[tuple[str, StageExecutor], ...]] = {
        "prepare": (
            ("sync-daily", _execute_daily),
            ("sync-reports", _execute_reports),
            ("parse-reports", _execute_parse),
        ),
        "sync-daily": (("sync-daily", _execute_daily),),
        "sync-sales-limits": (("sync-sales-limits", _execute_limits),),
        "sync-reports": (("sync-reports", _execute_reports),),
        "parse-reports": (("parse-reports", _execute_parse),),
    }
    try:
        return stages[operation]
    except KeyError as error:
        raise ValueError(f"unsupported data operation: {operation}") from error


def _execute_daily(session: Session, raw_root: Path, item: DataOperation) -> DataOperationResult:
    return sync_daily_data(
        session,
        raw_root,
        fund_codes=tuple(item.fund_codes),
        lookback_days=item.lookback_days,
    )


def _execute_limits(session: Session, raw_root: Path, item: DataOperation) -> DataOperationResult:
    return sync_sales_limits_data(
        session,
        raw_root,
        fund_codes=tuple(item.fund_codes),
    )


def _execute_reports(session: Session, raw_root: Path, item: DataOperation) -> DataOperationResult:
    return sync_reports_data(
        session,
        raw_root,
        fund_codes=tuple(item.fund_codes),
        year=_required_period(item)[0],
        quarter=_required_period(item)[1],
    )


def _execute_parse(session: Session, raw_root: Path, item: DataOperation) -> DataOperationResult:
    return parse_reports_data(
        session,
        raw_root,
        fund_codes=tuple(item.fund_codes),
        year=_required_period(item)[0],
        quarter=_required_period(item)[1],
    )


def _required_period(item: DataOperation) -> tuple[int, int]:
    if item.report_year is None or item.report_quarter is None:
        raise RuntimeError(f"data operation {item.id} has no report period")
    return item.report_year, item.report_quarter


def _required_operation(session: Session, operation_id: int) -> DataOperation:
    item = session.get(DataOperation, operation_id)
    if item is None:
        raise RuntimeError(f"data operation {operation_id} disappeared")
    return item


def _combined_result_status(results: list[DataOperationResult]) -> str:
    statuses = {result.status.lower() for result in results}
    if statuses == {"succeeded"}:
        return "succeeded"
    if statuses == {"failed"}:
        return "failed"
    return "partial"
