"""Explicitly authorized provisioning for a missing external PostgreSQL database."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from dataclasses import asdict, dataclass
from enum import StrEnum

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import get_settings

AUTO_CREATE_ENV = "QDII_AUTO_CREATE_DATABASE"
ADMIN_URL_ENV = "QDII_EXTERNAL_ADMIN_DATABASE_URL"


class ProvisionStatus(StrEnum):
    SKIPPED = "SKIPPED"
    EXISTING = "EXISTING"
    CREATED = "CREATED"


@dataclass(frozen=True, slots=True)
class ProvisionResult:
    status: ProvisionStatus
    database: str | None


def auto_create_enabled(raw_value: str | None) -> bool:
    normalized = (raw_value or "false").strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"{AUTO_CREATE_ENV} must be exactly true or false")


def provision_database(
    target_database_url: str,
    admin_database_url: str | None,
    *,
    authorized: bool,
) -> ProvisionResult:
    if not authorized:
        return ProvisionResult(ProvisionStatus.SKIPPED, database=None)

    target_url = _validated_postgresql_url(target_database_url, label="target")
    if admin_database_url is None or not admin_database_url.strip():
        raise ValueError(f"{ADMIN_URL_ENV} is required when {AUTO_CREATE_ENV}=true")
    admin_url = _validated_postgresql_url(admin_database_url, label="admin")
    _validate_same_server(target_url, admin_url)

    target_database = target_url.database
    target_owner = target_url.username
    if target_database is None or target_owner is None or not target_owner.strip():
        raise ValueError("target PostgreSQL URL must include a database and application user")
    admin_user = admin_url.username
    if admin_user is None or not admin_user.strip():
        raise ValueError("admin PostgreSQL URL must include an administrator user")
    if admin_user == target_owner:
        raise ValueError("admin and application PostgreSQL users must be different")
    if admin_url.database == target_database:
        raise ValueError("admin URL must connect to an existing maintenance database")

    conninfo = admin_url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(conninfo, autocommit=True) as connection:
        if _database_exists(connection, target_database):
            return ProvisionResult(ProvisionStatus.EXISTING, database=target_database)
        with suppress(psycopg.errors.DuplicateDatabase):
            connection.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(target_database),
                    sql.Identifier(target_owner),
                )
            )
        if not _database_exists(connection, target_database):
            raise RuntimeError("database creation returned without creating the target database")
    return ProvisionResult(ProvisionStatus.CREATED, database=target_database)


def _validated_postgresql_url(raw_url: str, *, label: str) -> URL:
    try:
        url = make_url(raw_url)
    except SQLAlchemyError as error:
        raise ValueError(f"{label} database URL is invalid") from error
    if url.get_backend_name() != "postgresql":
        raise ValueError(f"{label} database URL must use PostgreSQL")
    if url.database is None or not url.database.strip():
        raise ValueError(f"{label} PostgreSQL URL must include a database")
    return url


def _validate_same_server(target_url: URL, admin_url: URL) -> None:
    target_server = (target_url.host, target_url.port or 5432)
    admin_server = (admin_url.host, admin_url.port or 5432)
    if target_server != admin_server:
        raise ValueError("admin and target URLs must address the same PostgreSQL server")


def _database_exists(connection: psycopg.Connection[tuple[object, ...]], name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (name,),
        ).fetchone()
        is not None
    )


def main() -> int:
    try:
        result = provision_database(
            get_settings().database_url,
            os.getenv(ADMIN_URL_ENV),
            authorized=auto_create_enabled(os.getenv(AUTO_CREATE_ENV)),
        )
    except (psycopg.Error, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
            )
        )
        return 2
    print(json.dumps(asdict(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
