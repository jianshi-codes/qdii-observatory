from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.database_preflight import DatabaseReadiness


def test_ready_reports_database_and_migration_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main,
        "database_readiness",
        lambda _engine: DatabaseReadiness(
            ready=True,
            database="OK",
            migration="0006_generalize_universe",
        ),
    )

    with TestClient(main.create_app()) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "OK",
        "migration": "0006_generalize_universe",
    }


def test_ready_returns_503_when_database_is_not_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main,
        "database_readiness",
        lambda _engine: DatabaseReadiness(
            ready=False,
            database="ERROR",
            migration="UNKNOWN",
        ),
    )

    with TestClient(main.create_app()) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
