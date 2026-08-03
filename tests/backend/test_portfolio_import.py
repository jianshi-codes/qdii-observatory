from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import api as api_module
from backend.app.ingestion.catalog_pipeline import PublicImportResult
from backend.app.models import DailyFundNav, FundContract, FundShare, PortfolioPosition
from backend.app.portfolio_import import build_portfolio_preview, parse_portfolio_workbook

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "public"
    / "templates"
    / "portfolio-import-template.xlsx"
)


def _filled_workbook(
    *,
    share_code: str = "123456",
    platform: str = "测试平台",
) -> bytes:
    output = BytesIO()
    values = {
        "A5": share_code,
        "B5": platform,
        "C5": "2026-08-01",
        "D5": "CNY",
        "E5": "10000",
        "F5": "500",
        "G5": "0.05",
        "H5": "750",
        "I5": "100",
        "J5": "0.0015",
        "K5": "0.0015",
        "L5": "0.012",
        "M5": "0.002",
        "N5": "是",
    }
    with ZipFile(TEMPLATE) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                root = ET.fromstring(content)
                cells = {
                    cell.attrib["r"]: cell
                    for cell in root.findall(f".//{{{MAIN_NS}}}c")
                    if "r" in cell.attrib
                }
                for reference, value in values.items():
                    cell = cells[reference]
                    cell.attrib["t"] = "inlineStr"
                    for child in list(cell):
                        cell.remove(child)
                    inline = ET.SubElement(cell, f"{{{MAIN_NS}}}is")
                    text = ET.SubElement(inline, f"{{{MAIN_NS}}}t")
                    text.text = value
                content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(item, content)
    return output.getvalue()


def _seed_share(
    session: Session,
    *,
    share_code: str = "123456",
    selected: bool = False,
) -> FundContract:
    fund = FundContract(
        canonical_name="测试全球基金",
        manager_name="测试基金",
        representative_code=share_code,
        is_user_selected=selected,
        is_dependency=False,
    )
    session.add(fund)
    session.flush()
    share = FundShare(
        fund_contract_id=fund.id,
        share_code=share_code,
        currency="CNY",
    )
    session.add(share)
    session.flush()
    session.add(
        DailyFundNav(
            fund_share_id=share.id,
            nav_date=date(2026, 7, 31),
            unit_nav=Decimal("1.25"),
            source_provider="TEST",
            raw_payload_hash="a" * 64,
        )
    )
    session.commit()
    return fund


def test_portfolio_template_parses_typed_percentages_and_preview_restore(
    db_session: Session,
) -> None:
    fund = _seed_share(db_session)
    workbook = parse_portfolio_workbook(_filled_workbook())
    preview = build_portfolio_preview(db_session, workbook, SimpleNamespace())

    assert workbook.payload["positions"][0]["holding_return_pct"] == "5.00"
    assert workbook.payload["positions"][0]["purchase_fee_pct"] == "0.1500"
    assert preview["valid"] is True
    assert preview["positions"][0]["universe_action"] == "RESTORE"
    assert preview["positions"][0]["nav_action"] == "KEEP"
    assert preview["positions"][0]["snapshot_date"] == date(2026, 8, 1)
    assert fund.is_user_selected is False


def test_portfolio_preview_rejects_non_xlsx_content(client: TestClient) -> None:
    response = client.post(
        "/api/portfolio/import/preview",
        json={
            "filename": "portfolio.xlsx",
            "content_base64": base64.b64encode(b"not an xlsx").decode("ascii"),
        },
    )

    assert response.status_code == 422
    assert "无法读取 XLSX" in response.json()["detail"]


def test_confirm_portfolio_import_restores_fund_and_writes_position(
    client: TestClient,
    db_session: Session,
) -> None:
    fund = _seed_share(db_session)
    content = _filled_workbook()
    encoded = base64.b64encode(content).decode("ascii")
    preview = client.post(
        "/api/portfolio/import/preview",
        json={"filename": "portfolio.xlsx", "content_base64": encoded},
    )

    assert preview.status_code == 200
    assert preview.json()["valid"] is True
    confirm = client.post(
        "/api/portfolio/import/confirm",
        json={
            "filename": "portfolio.xlsx",
            "content_base64": encoded,
            "file_digest": preview.json()["file_digest"],
        },
    )

    assert confirm.status_code == 200
    assert confirm.json()["universe_restored"] == ["123456"]
    db_session.refresh(fund)
    assert fund.is_user_selected is True
    position = db_session.scalar(select(PortfolioPosition))
    assert position is not None
    assert position.reported_market_value == Decimal("10000.000000")
    assert position.reported_return_pct == Decimal("5.00000000")


def test_confirm_portfolio_import_adds_unknown_fund_and_syncs_nav(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    candidate = SimpleNamespace(
        fund_code="654321",
        fund_name="新增 QDII 基金",
        manager_name="新增基金公司",
        currency="CNY",
    )
    provider = SimpleNamespace(lookup=lambda _: SimpleNamespace(candidates=(candidate,)))
    client.app.dependency_overrides[api_module.get_fund_catalog_provider] = lambda: provider

    def fake_import_public_funds(
        session: Session,
        _provider: object,
        _raw_root: Path,
        codes: tuple[str, ...],
    ) -> PublicImportResult:
        assert codes == ("654321",)
        fund = FundContract(
            canonical_name=candidate.fund_name,
            manager_name=candidate.manager_name,
            representative_code=candidate.fund_code,
            is_user_selected=True,
        )
        session.add(fund)
        session.flush()
        session.add(
            FundShare(
                fund_contract_id=fund.id,
                share_code=candidate.fund_code,
                currency="CNY",
            )
        )
        session.commit()
        return PublicImportResult("succeeded", codes, {})

    def fake_sync_nav(session: Session, *args: object, **kwargs: object) -> SimpleNamespace:
        share = session.scalar(select(FundShare).where(FundShare.share_code == "654321"))
        assert share is not None
        session.add(
            DailyFundNav(
                fund_share_id=share.id,
                nav_date=date(2026, 7, 31),
                unit_nav=Decimal("1.10"),
                source_provider="TEST",
                raw_payload_hash="b" * 64,
            )
        )
        session.commit()
        return SimpleNamespace(status="succeeded")

    @contextmanager
    def fake_provider_client(*_names: str):
        yield SimpleNamespace()

    monkeypatch.setattr(api_module, "import_public_funds", fake_import_public_funds)
    monkeypatch.setattr(api_module, "sync_nav", fake_sync_nav)
    monkeypatch.setattr(api_module, "provider_client", fake_provider_client)
    monkeypatch.setattr(api_module, "raw_data_dir", lambda: tmp_path)
    content = _filled_workbook(share_code="654321")
    encoded = base64.b64encode(content).decode("ascii")
    preview = client.post(
        "/api/portfolio/import/preview",
        json={"filename": "portfolio.xlsx", "content_base64": encoded},
    )
    confirm = client.post(
        "/api/portfolio/import/confirm",
        json={
            "filename": "portfolio.xlsx",
            "content_base64": encoded,
            "file_digest": preview.json()["file_digest"],
        },
    )

    assert preview.json()["positions"][0]["universe_action"] == "ADD"
    assert confirm.status_code == 200
    assert confirm.json()["universe_added"] == ["654321"]
    assert confirm.json()["nav_synced"] == ["654321"]
    fund = db_session.scalar(
        select(FundContract).where(FundContract.representative_code == "654321")
    )
    assert fund is not None and fund.is_user_selected is True
    assert db_session.scalar(select(PortfolioPosition)) is not None
    client.app.dependency_overrides.pop(api_module.get_fund_catalog_provider, None)
