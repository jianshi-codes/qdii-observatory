"""Quarterly-report discovery using verified regulator page flows."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import unescape
from urllib.parse import urljoin

from backend.app.ingestion.http import ProviderHttpClient
from backend.app.ingestion.providers.base import (
    ProviderSchemaError,
    ReportCandidate,
)

TAG = re.compile(r"<[^>]+>")
WHITESPACE = re.compile(r"\s+")
ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
LINK = re.compile(
    r"<a\b[^>]*href=[\"'](?P<href>[^\"']*instance_show_pdf_id\.do\?instanceid=[^\"']+)[\"'][^>]*>(?P<title>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
DATE = re.compile(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}")


class CsrcReportProvider:
    """CSRC EID HTML/PDF flow observed from the official page on 2026-07-31."""

    name = "CSRC_EID"
    version = "fund-detail-html-v1"
    base_url = "http://eid.csrc.gov.cn/fund/disclose/"
    index_url = urljoin(base_url, "index.html")

    def __init__(self, http: ProviderHttpClient) -> None:
        self.http = http

    def discover(self, fund_code: str, year: int, quarter: int) -> list[ReportCandidate]:
        if len(fund_code) != 6 or not fund_code.isdigit():
            raise ValueError(f"Invalid fund code: {fund_code!r}")
        validate_url = urljoin(self.base_url, "validate_fund.do")
        validation = self.http.request(
            "POST",
            validate_url,
            data={"cFundCode": fund_code},
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": self.index_url,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            validation_data = json.loads(validation.content)
        except json.JSONDecodeError as error:
            raise ProviderSchemaError("CSRC fund validation response is not JSON") from error
        if not isinstance(validation_data, dict) or validation_data.get("isSuccess") is not True:
            raise ProviderSchemaError(
                f"CSRC does not recognize fund code {fund_code}: {validation_data!r}"
            )
        fund_id = validation_data.get("fundId")
        if not isinstance(fund_id, (int, str)) or not str(fund_id).isdigit():
            raise ProviderSchemaError("CSRC validation response has no numeric fundId")

        page_url = urljoin(self.base_url, f"fund_detail_search.do?cFundCode={fund_id}")
        page = self.http.request(
            "GET",
            page_url,
            headers={"Accept": "text/html,application/xhtml+xml", "Referer": self.index_url},
        )
        html = page.text
        expected = _quarter_tokens(year, quarter)
        candidates: list[ReportCandidate] = []
        for row_match in ROW.finditer(html):
            row_html = row_match.group(1)
            link = LINK.search(row_html)
            if link is None:
                continue
            title = _plain_text(link.group("title"))
            if "提示性公告" in title or re.search(r"旗下(?:部分)?基金", title):
                continue
            compact_title = re.sub(r"[\s：:（）()]+", "", title)
            if not any(token in compact_title for token in expected):
                continue
            date_match = DATE.search(_plain_text(row_html))
            published = None
            if date_match:
                published = datetime.fromisoformat(date_match.group()).replace(tzinfo=UTC)
            candidates.append(
                ReportCandidate(
                    provider_name=self.name,
                    provider_version=self.version,
                    fund_code=fund_code,
                    title=title,
                    public_available_at=published,
                    source_page_url=str(page.url),
                    document_url=urljoin(str(page.url), unescape(link.group("href"))),
                    mime_type="application/pdf",
                )
            )
        unique = {candidate.document_url: candidate for candidate in candidates}
        return list(unique.values())

    def download(self, candidate: ReportCandidate) -> bytes:
        response = self.http.request(
            "GET",
            candidate.document_url,
            headers={"Accept": "application/pdf", "Referer": candidate.source_page_url},
        )
        payload = response.content
        if not payload.startswith(b"%PDF-"):
            raise ProviderSchemaError(
                f"CSRC document is not a PDF: content-type={response.headers.get('content-type')!r}"
            )
        return payload


def _plain_text(fragment: str) -> str:
    return WHITESPACE.sub(" ", unescape(TAG.sub(" ", fragment))).strip()


def _quarter_tokens(year: int, quarter: int) -> tuple[str, ...]:
    chinese = {1: "一", 2: "二", 3: "三", 4: "四"}
    if quarter not in chinese:
        raise ValueError("quarter must be in 1..4")
    numeral = chinese[quarter]
    return (
        f"{year}年第{quarter}季度报告",
        f"{year}第{quarter}季度报告",
        f"{year}年第{numeral}季度报告",
        f"{year}第{numeral}季度报告",
        f"{year}年{numeral}季度报告",
        f"{year}{numeral}季度报告",
    )
