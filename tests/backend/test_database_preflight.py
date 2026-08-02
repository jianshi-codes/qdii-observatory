from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from backend.app.config import get_settings
from backend.app.database_preflight import (
    DatabaseState,
    database_readiness,
    inspect_database,
)


def _database_url(tmp_path: Path, name: str) -> str:
    return f"sqlite:///{tmp_path / name}"


def _upgrade(database_url: str, monkeypatch: pytest.MonkeyPatch, revision: str = "head") -> None:
    monkeypatch.setenv("QDII_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config()
    config.set_main_option("script_location", "migrations")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, revision)
    get_settings.cache_clear()


def test_preflight_accepts_empty_database(tmp_path: Path) -> None:
    engine = create_engine(_database_url(tmp_path, "empty.sqlite3"))

    result = inspect_database(engine)

    assert result.state == DatabaseState.EMPTY
    assert result.current_revision is None
    engine.dispose()


def test_preflight_rejects_unmanaged_tables(tmp_path: Path) -> None:
    engine = create_engine(_database_url(tmp_path, "unmanaged.sqlite3"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE legacy_fund (id INTEGER PRIMARY KEY)"))

    result = inspect_database(engine)

    assert result.state == DatabaseState.CONFLICT
    assert result.reason == "target schema contains tables but has no Alembic ownership record"
    engine.dispose()


def test_preflight_accepts_managed_older_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _database_url(tmp_path, "older.sqlite3")
    _upgrade(database_url, monkeypatch, "0001_initial_schema")
    engine = create_engine(database_url)

    result = inspect_database(engine)
    readiness = database_readiness(engine)

    assert result.state == DatabaseState.MANAGED
    assert result.current_revision == "0001_initial_schema"
    assert readiness.ready is False
    assert readiness.migration == "OUTDATED:0001_initial_schema"
    engine.dispose()


def test_preflight_accepts_current_managed_schema_and_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _database_url(tmp_path, "managed.sqlite3")
    _upgrade(database_url, monkeypatch)
    engine = create_engine(database_url)

    result = inspect_database(engine)
    readiness = database_readiness(engine)

    assert result.state == DatabaseState.MANAGED
    assert result.current_revision == result.head_revision
    assert readiness.ready is True
    assert readiness.database == "OK"
    assert readiness.migration == result.head_revision
    engine.dispose()


def test_preflight_rejects_unmanaged_table_in_managed_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _database_url(tmp_path, "managed-conflict.sqlite3")
    _upgrade(database_url, monkeypatch)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE other_application (id INTEGER PRIMARY KEY)"))

    result = inspect_database(engine)

    assert result.state == DatabaseState.CONFLICT
    assert result.reason == "target schema contains unmanaged tables: other_application"
    engine.dispose()


def test_preflight_rejects_unknown_alembic_revision(tmp_path: Path) -> None:
    engine = create_engine(_database_url(tmp_path, "unknown.sqlite3"))
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('unknown_revision')"))

    result = inspect_database(engine)

    assert result.state == DatabaseState.CONFLICT
    assert result.reason == "Alembic revision is not in this project's migration lineage"
    engine.dispose()


def test_preflight_rejects_head_schema_column_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = _database_url(tmp_path, "drift.sqlite3")
    _upgrade(database_url, monkeypatch)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE fund_contract RENAME COLUMN region TO drift_region")
        )

    result = inspect_database(engine)

    assert result.state == DatabaseState.CONFLICT
    assert result.reason is not None
    assert result.reason.startswith("head schema differs from application metadata (")
    engine.dispose()
