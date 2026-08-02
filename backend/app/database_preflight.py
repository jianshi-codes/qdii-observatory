"""Fail-closed database ownership checks for startup and readiness."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import SQLAlchemyError

from backend.app import models  # noqa: F401
from backend.app.database import Base, engine

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_VERSION_TABLE = "alembic_version"
CORE_TABLE_FINGERPRINTS: dict[str, frozenset[str]] = {
    "fund_contract": frozenset(
        {"id", "canonical_name", "manager_name", "representative_code"}
    ),
    "fund_share": frozenset({"id", "fund_contract_id", "share_code"}),
    "ingestion_run": frozenset({"id", "job_type", "status"}),
    "source_artifact": frozenset({"id", "source_provider", "source_url", "sha256"}),
}


class DatabaseState(StrEnum):
    EMPTY = "EMPTY"
    MANAGED = "MANAGED"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class DatabaseInspection:
    state: DatabaseState
    head_revision: str
    current_revision: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DatabaseReadiness:
    ready: bool
    database: str
    migration: str


def _migration_lineage() -> tuple[str, frozenset[str]]:
    config = Config()
    config.set_main_option("script_location", str(REPOSITORY_ROOT / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    head = scripts.get_current_head()
    if head is None:
        raise RuntimeError("Alembic migration history has no single head")
    lineage = frozenset(revision.revision for revision in scripts.iterate_revisions(head, "base"))
    return head, lineage


def inspect_database(target_engine: Engine) -> DatabaseInspection:
    head, lineage = _migration_lineage()
    inspector = inspect(target_engine)
    tables = set(inspector.get_table_names())
    if not tables:
        return DatabaseInspection(DatabaseState.EMPTY, head_revision=head)
    if ALEMBIC_VERSION_TABLE not in tables:
        return DatabaseInspection(
            DatabaseState.CONFLICT,
            head_revision=head,
            reason="target schema contains tables but has no Alembic ownership record",
        )

    with target_engine.connect() as connection:
        revisions = (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        )
    if len(revisions) != 1:
        return DatabaseInspection(
            DatabaseState.CONFLICT,
            head_revision=head,
            reason="Alembic ownership record must contain exactly one revision",
        )
    current = str(revisions[0])
    if current not in lineage:
        return DatabaseInspection(
            DatabaseState.CONFLICT,
            head_revision=head,
            current_revision=current,
            reason="Alembic revision is not in this project's migration lineage",
        )

    application_tables = tables - {ALEMBIC_VERSION_TABLE}
    expected_tables = set(Base.metadata.tables)
    unexpected_tables = sorted(application_tables - expected_tables)
    if unexpected_tables:
        return DatabaseInspection(
            DatabaseState.CONFLICT,
            head_revision=head,
            current_revision=current,
            reason=f"target schema contains unmanaged tables: {', '.join(unexpected_tables)}",
        )

    fingerprint_error = _fingerprint_error(inspector)
    if fingerprint_error is not None:
        return DatabaseInspection(
            DatabaseState.CONFLICT,
            head_revision=head,
            current_revision=current,
            reason=fingerprint_error,
        )

    if current == head:
        schema_error = _head_schema_error(target_engine)
        if schema_error is not None:
            return DatabaseInspection(
                DatabaseState.CONFLICT,
                head_revision=head,
                current_revision=current,
                reason=schema_error,
            )
    return DatabaseInspection(
        DatabaseState.MANAGED,
        head_revision=head,
        current_revision=current,
    )


def _fingerprint_error(inspector: Inspector) -> str | None:
    table_names = set(inspector.get_table_names())
    for table_name, required_columns in CORE_TABLE_FINGERPRINTS.items():
        if table_name not in table_names:
            return f"managed schema is missing core table: {table_name}"
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        missing_columns = sorted(required_columns - actual_columns)
        if missing_columns:
            return f"core table {table_name} is missing columns: {', '.join(missing_columns)}"
    return None


def _head_schema_error(target_engine: Engine) -> str | None:
    with target_engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)
    if differences:
        return f"head schema differs from application metadata ({len(differences)} differences)"
    return None


def database_readiness(target_engine: Engine) -> DatabaseReadiness:
    head, _ = _migration_lineage()
    try:
        with target_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            current = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            connection.execute(text("SELECT 1 FROM fund_contract LIMIT 1"))
    except SQLAlchemyError:
        return DatabaseReadiness(ready=False, database="ERROR", migration="UNKNOWN")
    if str(current) != head:
        return DatabaseReadiness(
            ready=False,
            database="OK",
            migration=f"OUTDATED:{current}",
        )
    return DatabaseReadiness(ready=True, database="OK", migration=str(current))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-head",
        action="store_true",
        help="Require a fully migrated and structurally current managed database.",
    )
    args = parser.parse_args(argv)
    try:
        result = inspect_database(engine)
    except SQLAlchemyError as error:
        print(
            json.dumps(
                {
                    "state": DatabaseState.CONFLICT,
                    "reason": f"database inspection failed: {type(error).__name__}",
                }
            )
        )
        return 2
    print(json.dumps(asdict(result)))
    if result.state == DatabaseState.CONFLICT:
        return 2
    if args.require_head and (
        result.state != DatabaseState.MANAGED
        or result.current_revision != result.head_revision
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
