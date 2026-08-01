from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.app.ingestion.providers.base import ProviderSchemaError
from backend.app.ingestion.providers.nav import EastmoneyChartNavProvider, EastmoneyNavProvider
from backend.app.ingestion.providers.reports import CsrcReportProvider


class FixtureCsrcHttp:
    def __init__(self, validation: dict[str, Any], detail_html: str, pdf: bytes) -> None:
        self.validation = copy.deepcopy(validation)
        self.detail_html = detail_html
        self.pdf = pdf
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **_: Any) -> httpx.Response:
        self.calls.append((method, url))
        request = httpx.Request(method, url)
        if url.endswith("validate_fund.do"):
            payload = json.dumps(self.validation, ensure_ascii=False).encode()
            return httpx.Response(
                200,
                content=payload,
                headers={"content-type": "application/json"},
                request=request,
            )
        if "fund_detail_search.do" in url:
            return httpx.Response(
                200,
                text=self.detail_html,
                headers={"content-type": "text/html; charset=utf-8"},
                request=request,
            )
        if "instance_show_pdf_id.do" in url:
            return httpx.Response(
                200,
                content=self.pdf,
                headers={"content-type": "application/pdf"},
                request=request,
            )
        raise AssertionError(f"Unexpected fixture request: {method} {url}")


def _csrc_http(
    provider_fixture_dir: Path,
) -> FixtureCsrcHttp:
    validation = json.loads(
        (provider_fixture_dir / "csrc-validate-017653.json").read_text(encoding="utf-8")
    )
    detail_html = (provider_fixture_dir / "csrc-fund-detail-017653.html").read_text(
        encoding="utf-8"
    )
    pdf = b"%PDF-1.4\nsynthetic transport fixture\n%%EOF\n"
    return FixtureCsrcHttp(validation, detail_html, pdf)


def test_csrc_fixture_discovers_only_requested_quarter_and_downloads_pdf(
    provider_fixture_dir: Path,
) -> None:
    http = _csrc_http(provider_fixture_dir)
    provider = CsrcReportProvider(http)  # type: ignore[arg-type]

    candidates = provider.discover("017653", 2026, 2)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.fund_code == "017653"
    assert "2026 年第 2 季度报告" in candidate.title
    assert candidate.public_available_at == datetime(2026, 7, 20, tzinfo=UTC)
    assert candidate.source_page_url.endswith("fund_detail_search.do?cFundCode=17653")
    assert candidate.document_url.endswith("instance_show_pdf_id.do?instanceid=2026Q2-017653")
    assert provider.download(candidate).startswith(b"%PDF-")
    assert [method for method, _ in http.calls] == ["POST", "GET", "GET"]


def test_csrc_fixture_rejects_validation_schema_drift(
    provider_fixture_dir: Path,
) -> None:
    http = _csrc_http(provider_fixture_dir)
    http.validation.pop("fundId")
    provider = CsrcReportProvider(http)  # type: ignore[arg-type]

    with pytest.raises(ProviderSchemaError, match="no numeric fundId"):
        provider.discover("017653", 2026, 2)


def test_csrc_discovery_excludes_manager_batch_notice(
    provider_fixture_dir: Path,
) -> None:
    http = _csrc_http(provider_fixture_dir)
    notice = """
      <tr><td>2026-07-20</td><td>
        <a href="instance_show_pdf_id.do?instanceid=batch-notice">
          创金合信基金旗下部分基金2026年第2季度报告提示性公告
        </a>
      </td></tr>
    """
    http.detail_html = http.detail_html.replace("</table>", f"{notice}</table>")
    provider = CsrcReportProvider(http)  # type: ignore[arg-type]

    candidates = provider.discover("017653", 2026, 2)

    assert [candidate.title for candidate in candidates] == [
        "创金合信全球芯片产业股票型发起式证券投资基金（QDII）2026 年第 2 季度报告"
    ]


def test_nav_provider_parses_fixture_pagination_decimals_and_timestamps(
    fixture_nav_provider: tuple[EastmoneyNavProvider, Any],
) -> None:
    provider, http = fixture_nav_provider

    first = provider.fetch_page(
        "017653",
        1,
        2,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 3),
    )
    second = provider.fetch_page("017653", 2, 2)

    assert http.requested_pages == [1, 2]
    assert first.page_index == 1
    assert first.total_pages == 2
    assert first.total_records == 3
    assert [row.nav_date for row in first.records] == [date(2024, 1, 3), date(2024, 1, 2)]
    assert first.records[0].unit_nav.as_tuple().exponent == -4
    assert first.records[0].unit_nav == Decimal("1.2100")
    assert first.records[0].published_daily_return_pct == Decimal("10.0000")
    assert first.records[0].source_published_at == datetime(
        2024, 1, 4, 8, tzinfo=timezone(timedelta(hours=8))
    )
    assert second.page_index == 2
    assert len(second.records) == 1
    assert second.records[0].published_daily_return_pct is None


def test_nav_provider_rejects_page_mismatch_and_missing_rows(
    fixture_nav_provider: tuple[EastmoneyNavProvider, Any],
) -> None:
    provider, http = fixture_nav_provider
    http.documents[1]["PageIndex"] = 2

    with pytest.raises(ProviderSchemaError, match="NAV page mismatch"):
        provider.fetch_page("017653", 1, 2)

    http.documents[1]["PageIndex"] = 1
    http.documents[1]["Data"].pop("LSJZList")
    with pytest.raises(ProviderSchemaError, match=r"Data\.LSJZList"):
        provider.fetch_page("017653", 1, 2)


class FixtureChartNavHttp:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def request(self, method: str, url: str, **_: Any) -> httpx.Response:
        request = httpx.Request(method, url)
        return httpx.Response(
            200,
            content=self.payload,
            headers={"content-type": "application/javascript; charset=utf-8"},
            request=request,
        )


def _chart_payload(*, code: str = "017653", duplicate_date: bool = False) -> bytes:
    second_timestamp = 1785456000000 if duplicate_date else 1785542400000
    return (
        f'var fS_code = "{code}";\n'
        "var Data_netWorthTrend = ["
        '{"x":1785456000000,"y":1.2,"equityReturn":null},'
        f'{{"x":{second_timestamp},"y":1.2123,"equityReturn":1.025}}];\n'
        "var Data_ACWorthTrend = [[1785456000000,1.2],[1785542400000,1.2123]];\n"
    ).encode()


def test_chart_nav_provider_parses_full_history_and_filters_dates() -> None:
    provider = EastmoneyChartNavProvider(FixtureChartNavHttp(_chart_payload()))  # type: ignore[arg-type]

    page = provider.fetch_page(
        "017653",
        1,
        500,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 1),
    )

    assert page.provider_name == "EASTMONEY_NAV_CHART"
    assert page.total_pages == 1
    assert page.total_records == 1
    assert page.mime_type == "application/javascript"
    assert page.records[0].nav_date == date(2026, 8, 1)
    assert page.records[0].unit_nav == Decimal("1.2123")
    assert page.records[0].accumulated_nav == Decimal("1.2123")
    assert page.records[0].published_daily_return_pct == Decimal("1.025")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_chart_payload(code="000001"), "code does not match"),
        (_chart_payload(duplicate_date=True), "duplicate date"),
        (
            b'var fS_code = "017653"; var Data_netWorthTrend = []; var Data_ACWorthTrend = [];',
            "no unit-NAV rows",
        ),
    ],
)
def test_chart_nav_provider_rejects_schema_drift(payload: bytes, message: str) -> None:
    provider = EastmoneyChartNavProvider(FixtureChartNavHttp(payload))  # type: ignore[arg-type]

    with pytest.raises(ProviderSchemaError, match=message):
        provider.fetch_page("017653", 1, 500)


def test_chart_nav_provider_accepts_missing_accumulated_nav() -> None:
    payload = _chart_payload().replace(b"[1785542400000,1.2123]", b"[1785542400000,null]")
    provider = EastmoneyChartNavProvider(FixtureChartNavHttp(payload))  # type: ignore[arg-type]

    page = provider.fetch_page("017653", 1, 500)

    assert page.records[-1].accumulated_nav is None
