from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api import get_fund_catalog_provider
from backend.app.ingestion.providers.base import (
    FundCatalogSnapshot,
    FundCompanyChoice,
    PublicFundCandidate,
)
from backend.app.models import FundContract, SourceArtifact


class FakeCatalogProvider:
    name = "EASTMONEY_FUND_CATALOG"
    version = "fixture-v1"

    def companies(self) -> tuple[FundCompanyChoice, ...]:
        return (FundCompanyChoice("80009999", "示例基金"),)

    def discover_company(self, company_code: str) -> FundCatalogSnapshot:
        assert company_code == "80009999"
        return self._snapshot()

    def discover_public(self, source_category: str | None = None) -> FundCatalogSnapshot:
        assert source_category in (None, "311")
        return self._snapshot()

    def lookup(self, fund_code: str) -> FundCatalogSnapshot:
        assert fund_code == "900001"
        return self._snapshot()

    def _snapshot(self) -> FundCatalogSnapshot:
        return FundCatalogSnapshot(
            candidates=(
                PublicFundCandidate(
                    fund_code="900001",
                    fund_name="示例全球科技股票(QDII)A",
                    manager_code="80009999",
                    manager_name="示例基金",
                    category="QDII-普通股票",
                    research_scope="TECHNOLOGY",
                    currency="CNY",
                    wrapper_type="DIRECT",
                    source_url="https://example.invalid/public-fund/900001",
                ),
            ),
            raw_payload=b'{"fixture":"public-fund"}',
            source_url="https://example.invalid/public-fund/900001",
            mime_type="application/json",
        )


def test_catalog_api_supports_choices_lookup_and_explicit_import(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_root = tmp_path / "raw"
    monkeypatch.setattr("backend.app.api.raw_data_dir", lambda: raw_root)
    client.app.dependency_overrides[get_fund_catalog_provider] = FakeCatalogProvider

    options = client.get("/api/fund-catalog/options")
    candidates = client.get(
        "/api/fund-catalog/candidates",
        params={
            "company_code": "80009999",
            "source_category": "311",
            "category": "QDII-普通股票",
            "research_scope": "TECHNOLOGY",
        },
    )
    source_candidates = client.get(
        "/api/fund-catalog/candidates",
        params={"source_category": "311"},
    )
    lookup = client.get("/api/fund-catalog/lookup/900001")
    imported = client.post("/api/fund-catalog/import", json={"fund_codes": ["900001"]})

    assert options.status_code == 200
    assert options.json()["companies"] == [
        {"company_code": "80009999", "company_name": "示例基金"}
    ]
    assert options.json()["source_categories"][1] == {
        "value": "311",
        "label": "全球股票",
    }
    assert candidates.status_code == 200
    assert candidates.json()["items"][0]["research_scope"] == "TECHNOLOGY"
    assert source_candidates.status_code == 200
    assert source_candidates.json()["items"][0]["fund_code"] == "900001"
    assert lookup.status_code == 200
    assert lookup.json()["fund_code"] == "900001"
    assert imported.status_code == 200
    assert imported.json() == {
        "status": "succeeded",
        "imported_codes": ["900001"],
        "failures": {},
    }
    assert db_session.scalar(select(FundContract.representative_code)) == "900001"
    assert db_session.scalar(select(SourceArtifact.source_url)) == (
        "https://example.invalid/public-fund/900001"
    )
