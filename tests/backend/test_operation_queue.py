from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from backend.app import operation_queue
from backend.app.data_operations import DataOperationResult
from backend.app.models import DataOperation, IngestionRun
from backend.app.operation_queue import OperationInProgressError


def test_durable_operation_is_claimed_and_completed(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    queued = operation_queue.enqueue_operation(
        db_session,
        operation="sync-daily",
        fund_codes=("100055",),
        lookback_days=10,
        report_year=2026,
        report_quarter=2,
    )

    def execute(
        session: Session,
        raw_root: Path,
        item: DataOperation,
    ) -> DataOperationResult:
        assert raw_root == tmp_path
        assert item.fund_codes == ["100055"]
        run = IngestionRun(
            job_type="sync_nav",
            status="succeeded",
            parameters={},
            records_seen=1,
            records_written=5,
            records_failed=0,
        )
        session.add(run)
        session.commit()
        return DataOperationResult(
            operation="sync_daily",
            status="succeeded",
            fund_codes=("100055",),
            runs=(run,),
        )

    monkeypatch.setattr(
        operation_queue,
        "_stages",
        lambda operation: (("sync-daily", execute),),
    )

    assert operation_queue.claim_next_operation(db_session) == queued.id
    completed = operation_queue.execute_operation(db_session, queued.id, tmp_path)

    assert completed.status == "succeeded"
    assert completed.active_slot is None
    assert completed.stage_completed == 1
    assert completed.run_ids
    assert completed.records_written == 5


def test_active_slot_rejects_a_second_operation_and_recovers_restart(
    db_session: Session,
) -> None:
    first = operation_queue.enqueue_operation(
        db_session,
        operation="sync-reports",
        fund_codes=("100055",),
        lookback_days=10,
        report_year=2026,
        report_quarter=2,
    )
    with pytest.raises(OperationInProgressError):
        operation_queue.enqueue_operation(
            db_session,
            operation="sync-sales-limits",
            fund_codes=("100055",),
            lookback_days=10,
            report_year=2026,
            report_quarter=2,
        )
    assert operation_queue.claim_next_operation(db_session) == first.id
    assert operation_queue.recover_interrupted_operations(db_session) == 1
    recovered = db_session.get(DataOperation, first.id)
    assert recovered is not None
    assert recovered.status == "failed"
    assert recovered.active_slot is None
    assert "worker restarted" in str(recovered.error_message)
