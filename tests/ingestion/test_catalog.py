from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ingestion.catalog_pipeline import import_public_funds
from backend.app.ingestion.providers.base import ProviderSchemaError
from backend.app.ingestion.providers.catalog import EastmoneyFundCatalogProvider
from backend.app.models import FundContract, FundShare, IngestionRun, SourceArtifact


class FixtureCatalogHttp:
    def __init__(self, fixture_dir: Path) -> None:
        self.fixture_dir = fixture_dir

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        **_: Any,
    ) -> httpx.Response:
        if url.endswith("FundCommpanyInfo.js"):
            filename = "eastmoney-fund-companies.js"
            content_type = "application/javascript; charset=utf-8"
        elif "/Company/f10/" in url:
            filename = "eastmoney-company-funds.html"
            content_type = "text/html; charset=utf-8"
        elif url.endswith("Fund_JJJZ_Data.aspx"):
            assert params is not None
            assert params["t"] == "10"
            assert params["lx"] == "7"
            assert params["feature"] == "311"
            filename = "eastmoney-qdii-catalog.js"
            content_type = "application/javascript; charset=utf-8"
        else:
            assert params == {"m": "1", "key": "900001"}
            filename = "eastmoney-fund-search.json"
            content_type = "application/json; charset=utf-8"
        request = httpx.Request(method, url, params=params)
        return httpx.Response(
            200,
            content=(self.fixture_dir / filename).read_bytes(),
            headers={"content-type": content_type},
            request=request,
        )


def test_catalog_discovers_companies_qdii_rows_and_exact_code(
    provider_fixture_dir: Path,
) -> None:
    provider = EastmoneyFundCatalogProvider(FixtureCatalogHttp(provider_fixture_dir))  # type: ignore[arg-type]

    assert [(item.company_code, item.company_name) for item in provider.companies()] == [
        ("80009999", "示例基金")
    ]
    company = provider.discover_company("80009999")
    assert [item.fund_code for item in company.candidates] == ["900001"]
    assert company.candidates[0].research_scope == "TECHNOLOGY"
    assert company.candidates[0].category == "QDII-普通股票"

    public = provider.discover_public("311")
    assert [item.fund_code for item in public.candidates] == ["900001"]
    assert public.candidates[0].manager_name is None
    assert public.candidates[0].category == "全球股票"

    exact = provider.lookup("900001")
    assert exact.candidates[0].manager_name == "示例基金"
    assert exact.candidates[0].currency == "CNY"


def test_catalog_fails_closed_when_company_wrapper_changes(
    provider_fixture_dir: Path,
) -> None:
    class BrokenHttp(FixtureCatalogHttp):
        def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            response = super().request(method, url, **kwargs)
            if url.endswith("FundCommpanyInfo.js"):
                return httpx.Response(
                    200,
                    content=b"window.changed=[];",
                    request=response.request,
                )
            return response

    provider = EastmoneyFundCatalogProvider(BrokenHttp(provider_fixture_dir))  # type: ignore[arg-type]
    with pytest.raises(ProviderSchemaError, match="wrapper changed"):
        provider.companies()


def test_public_catalog_deduplicates_rows_before_returning_candidates(
    provider_fixture_dir: Path,
) -> None:
    class DuplicateCatalogHttp(FixtureCatalogHttp):
        def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            response = super().request(method, url, **kwargs)
            if url.endswith("Fund_JJJZ_Data.aspx"):
                return httpx.Response(
                    200,
                    content=(
                        b'var db={datas:[["900001","Example QDII"],'
                        b'["900001","Example QDII"]],count:[],record:"2"};'
                    ),
                    headers={"content-type": "application/javascript; charset=utf-8"},
                    request=response.request,
                )
            return response

    provider = EastmoneyFundCatalogProvider(  # type: ignore[arg-type]
        DuplicateCatalogHttp(provider_fixture_dir)
    )

    assert [item.fund_code for item in provider.discover_public("311").candidates] == [
        "900001"
    ]


def test_public_catalog_fetches_every_bounded_page(provider_fixture_dir: Path) -> None:
    class PaginatedCatalogHttp(FixtureCatalogHttp):
        def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
            if not url.endswith("Fund_JJJZ_Data.aspx"):
                return super().request(method, url, **kwargs)
            params = kwargs["params"]
            page_number = int(params["page"].split(",", 1)[0])
            start = 1 if page_number == 1 else 201
            end = 200 if page_number == 1 else 201
            rows = [[f"{code:06d}", f"Example QDII {code}"] for code in range(start, end + 1)]
            content = (
                f'var db={{datas:{json.dumps(rows)},count:[],record:"201"}};'.encode()
            )
            return httpx.Response(
                200,
                content=content,
                headers={"content-type": "application/javascript; charset=utf-8"},
                request=httpx.Request(method, url, params=params),
            )

    provider = EastmoneyFundCatalogProvider(  # type: ignore[arg-type]
        PaginatedCatalogHttp(provider_fixture_dir)
    )

    assert len(provider.discover_public("311").candidates) == 201


def test_public_import_archives_source_and_is_idempotent(
    db_session: Session,
    provider_fixture_dir: Path,
    tmp_path: Path,
) -> None:
    provider = EastmoneyFundCatalogProvider(FixtureCatalogHttp(provider_fixture_dir))  # type: ignore[arg-type]

    first = import_public_funds(db_session, provider, tmp_path / "raw", ("900001",))
    second = import_public_funds(db_session, provider, tmp_path / "raw", ("900001",))

    assert first.status == second.status == "succeeded"
    assert db_session.scalars(select(FundContract)).all()[0].manager_name == "示例基金"
    assert db_session.scalars(select(FundShare)).all()[0].share_code == "900001"
    assert len(db_session.scalars(select(SourceArtifact)).all()) == 1
    assert len(db_session.scalars(select(IngestionRun)).all()) == 2
