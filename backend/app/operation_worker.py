"""Single durable data-operation worker used by Compose."""

from __future__ import annotations

import json
import time

from backend.app.database import SessionLocal
from backend.app.ingestion.storage import raw_data_dir
from backend.app.operation_queue import (
    claim_next_operation,
    execute_operation,
    recover_interrupted_operations,
)


def run_once() -> bool:
    with SessionLocal() as session:
        operation_id = claim_next_operation(session)
        if operation_id is None:
            return False
        result = execute_operation(session, operation_id, raw_data_dir())
        print(
            json.dumps(
                {
                    "operation_id": result.id,
                    "operation": result.operation,
                    "status": result.status,
                    "records_written": result.records_written,
                    "records_failed": result.records_failed,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        return True


def main() -> None:
    with SessionLocal() as session:
        recovered = recover_interrupted_operations(session)
    print(json.dumps({"worker": "ready", "recovered": recovered}), flush=True)
    while True:
        if not run_once():
            time.sleep(1)


if __name__ == "__main__":
    main()
