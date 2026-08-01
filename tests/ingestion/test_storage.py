from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.ingestion import storage as storage_module
from backend.app.ingestion.storage import StoragePreflightError, storage_preflight


def test_explicit_missing_external_storage_fails_without_creating_or_falling_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_pg = tmp_path / "external-volume" / "postgres"
    missing_raw = tmp_path / "external-volume" / "raw"
    monkeypatch.setenv("QDII_PG_VOLUME_TYPE", "bind")
    monkeypatch.setenv("QDII_PG_DATA_SOURCE", str(missing_pg))
    monkeypatch.setenv("QDII_RAW_DATA_DIR", str(missing_raw))

    with pytest.raises(
        StoragePreflightError,
        match=r"QDII_PG_DATA_SOURCE does not exist.*External paths are never auto-created",
    ):
        storage_preflight(min_free_bytes=0)

    assert not missing_pg.exists()
    assert not missing_raw.exists()


def test_explicit_external_path_on_system_filesystem_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("QDII_SHARED_POSTGRES_CONTAINER", "")
    monkeypatch.setenv("QDII_PG_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QDII_RAW_DATA_DIR", str(tmp_path))

    with pytest.raises(StoragePreflightError, match="not a mounted external volume"):
        storage_preflight(min_free_bytes=0)


def test_default_shared_postgres_mode_only_checks_raw_artifact_storage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing_pg = tmp_path / "postgres-owned-by-shared-container"
    raw = tmp_path / "raw"
    monkeypatch.setattr(storage_module, "repository_root", lambda: tmp_path)
    monkeypatch.delenv("QDII_SHARED_POSTGRES_CONTAINER", raising=False)
    monkeypatch.setenv("QDII_PG_DATA_DIR", str(missing_pg))
    monkeypatch.setenv("QDII_RAW_DATA_DIR", str(raw))

    targets = storage_preflight(min_free_bytes=0)

    assert [target.name for target in targets] == ["QDII_RAW_DATA_DIR"]
    assert targets[0].path == raw
    assert raw.is_dir()
    assert not missing_pg.exists()
