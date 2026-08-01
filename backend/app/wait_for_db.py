"""Wait for the configured database before migrations and API startup."""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.database import engine


def main(*, attempts: int = 60, delay_seconds: float = 1.0) -> int:
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return 0
        except SQLAlchemyError:
            if attempt == attempts:
                raise
            time.sleep(delay_seconds)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
