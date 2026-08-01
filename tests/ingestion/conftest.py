from __future__ import annotations

import copy
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models  # noqa: F401
from backend.app.database import Base
from backend.app.ingestion.providers.nav import EastmoneyNavProvider

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class FixtureNavHttp:
    def __init__(self, documents: dict[int, dict[str, Any]]) -> None:
        self.documents = copy.deepcopy(documents)
        self.requested_pages: list[int] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        **_: Any,
    ) -> httpx.Response:
        page_index = int((params or {})["pageIndex"])
        self.requested_pages.append(page_index)
        payload = json.dumps(
            self.documents[page_index], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        request = httpx.Request(method, url, params=params)
        return httpx.Response(
            200,
            content=payload,
            headers={"content-type": "application/json; charset=utf-8"},
            request=request,
        )


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="session")
def universe_path() -> Path:
    path = REPOSITORY_ROOT / "examples" / "universe.sample.csv"
    assert path.is_file()
    return path


@pytest.fixture(scope="session")
def provider_fixture_dir() -> Path:
    path = Path(__file__).resolve().parent / "fixtures" / "providers"
    assert path.is_dir()
    return path


@pytest.fixture
def fixture_nav_provider(
    provider_fixture_dir: Path,
) -> tuple[EastmoneyNavProvider, FixtureNavHttp]:
    documents = {
        page_index: json.loads(
            (provider_fixture_dir / f"eastmoney-nav-page-{page_index}.json").read_text(
                encoding="utf-8"
            )
        )
        for page_index in (1, 2)
    }
    http = FixtureNavHttp(documents)
    return EastmoneyNavProvider(http), http  # type: ignore[arg-type]
