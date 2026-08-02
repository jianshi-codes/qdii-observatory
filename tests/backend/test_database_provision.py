from __future__ import annotations

from typing import Any

import pytest

from backend.app import database_provision
from backend.app.database_provision import ProvisionStatus

TARGET_URL = "postgresql+psycopg://qdii_app:app-password@db.example:5432/qdii_observatory"
ADMIN_URL = "postgresql+psycopg://qdii_admin:admin-password@db.example:5432/postgres"


class FakeResult:
    def __init__(self, row: tuple[int] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[int] | None:
        return self._row


class FakeConnection:
    def __init__(self, *, database_exists: bool) -> None:
        self.database_exists = database_exists
        self.created = False

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: object, params: object = None) -> FakeResult:
        if isinstance(query, str) and query.startswith("SELECT 1 FROM pg_database"):
            return FakeResult((1,) if self.database_exists else None)
        self.created = True
        self.database_exists = True
        return FakeResult(None)


def test_auto_create_flag_is_strict() -> None:
    assert database_provision.auto_create_enabled(None) is False
    assert database_provision.auto_create_enabled("false") is False
    assert database_provision.auto_create_enabled("TRUE") is True
    with pytest.raises(ValueError, match="must be exactly true or false"):
        database_provision.auto_create_enabled("yes")


def test_provision_skips_without_explicit_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        database_provision.psycopg,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("admin connection must not be opened"),
    )

    result = database_provision.provision_database(
        TARGET_URL,
        None,
        authorized=False,
    )

    assert result.status == ProvisionStatus.SKIPPED
    assert result.database is None


def test_provision_requires_separate_admin_url() -> None:
    with pytest.raises(ValueError, match="is required"):
        database_provision.provision_database(TARGET_URL, None, authorized=True)
    with pytest.raises(ValueError, match="must be different"):
        database_provision.provision_database(TARGET_URL, TARGET_URL, authorized=True)
    with pytest.raises(ValueError, match="maintenance database"):
        database_provision.provision_database(
            TARGET_URL,
            "postgresql+psycopg://qdii_admin:password@db.example:5432/qdii_observatory",
            authorized=True,
        )


def test_provision_rejects_invalid_or_non_postgresql_target() -> None:
    with pytest.raises(ValueError, match="target database URL is invalid"):
        database_provision.provision_database("not a url", ADMIN_URL, authorized=True)
    with pytest.raises(ValueError, match="must use PostgreSQL"):
        database_provision.provision_database(
            "sqlite:///local.db",
            ADMIN_URL,
            authorized=True,
        )


def test_provision_rejects_admin_url_for_another_server() -> None:
    with pytest.raises(ValueError, match="same PostgreSQL server"):
        database_provision.provision_database(
            TARGET_URL,
            "postgresql+psycopg://admin:password@other.example:5432/postgres",
            authorized=True,
        )


def test_provision_preserves_existing_database(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection(database_exists=True)
    captured: dict[str, Any] = {}

    def fake_connect(conninfo: str, *, autocommit: bool) -> FakeConnection:
        captured.update(conninfo=conninfo, autocommit=autocommit)
        return connection

    monkeypatch.setattr(database_provision.psycopg, "connect", fake_connect)

    result = database_provision.provision_database(
        TARGET_URL,
        ADMIN_URL,
        authorized=True,
    )

    assert result.status == ProvisionStatus.EXISTING
    assert result.database == "qdii_observatory"
    assert connection.created is False
    assert captured["autocommit"] is True


def test_provision_creates_missing_database(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = FakeConnection(database_exists=False)
    monkeypatch.setattr(
        database_provision.psycopg,
        "connect",
        lambda *_args, **_kwargs: connection,
    )

    result = database_provision.provision_database(
        TARGET_URL,
        ADMIN_URL,
        authorized=True,
    )

    assert result.status == ProvisionStatus.CREATED
    assert result.database == "qdii_observatory"
    assert connection.created is True
