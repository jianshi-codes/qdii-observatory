"""Public QDII catalog discovery with strict source-schema validation."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any

from backend.app.ingestion.http import ProviderHttpClient
from backend.app.ingestion.providers.base import (
    FundCatalogSnapshot,
    FundCompanyChoice,
    ProviderSchemaError,
    PublicFundCandidate,
)

FUND_CODE = re.compile(r"^[0-9]{6}$")
COMPANY_CODE = re.compile(r"^[0-9]{8}$")
COMPANY_DOCUMENT = re.compile(
    r"^\s*var\s+FundCommpanyInfos\s*=\s*(\[.*\])\s*;?\s*$",
    re.DOTALL,
)
PUBLIC_CATALOG_DOCUMENT = re.compile(r"datas:(\[.*?\]),count:", re.DOTALL)
PUBLIC_CATALOG_RECORD = re.compile(r',record:"([0-9]+)"')

RESEARCH_SCOPES = (
    ("ALL", "全部 QDII"),
    ("TECHNOLOGY", "名称关键词：科技 / 数字经济"),
    ("EQUITY", "权益"),
    ("FIXED_INCOME", "固收"),
    ("COMMODITY", "商品"),
    ("REAL_ESTATE", "房地产 / REITs"),
    ("OTHER", "其他"),
)

SOURCE_CATEGORIES = (
    ("ALL", "全部来源分类"),
    ("311", "全球股票"),
    ("312", "亚太股票"),
    ("313", "大中华区股票"),
    ("317", "美国股票"),
    ("320", "股债混合"),
    ("330", "债券"),
    ("340", "商品"),
)
SOURCE_CATEGORY_LABELS = dict(SOURCE_CATEGORIES)
PUBLIC_CATALOG_PAGE_SIZE = 200
PUBLIC_CATALOG_MAX_PAGES = 5


class EastmoneyFundCatalogProvider:
    """Discover public fund metadata without treating the source as authoritative advice."""

    name = "EASTMONEY_FUND_CATALOG"
    version = "public-list-company-f10-search-v2"
    companies_endpoint = "https://fund.eastmoney.com/api/static/FundCommpanyInfo.js"
    company_endpoint = "https://fund.eastmoney.com/Company/f10/jjjz_{company_code}.html"
    public_catalog_endpoint = "https://fund.eastmoney.com/Data/Fund_JJJZ_Data.aspx"
    search_endpoint = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"

    def __init__(self, http: ProviderHttpClient) -> None:
        self.http = http

    def companies(self) -> tuple[FundCompanyChoice, ...]:
        response = self.http.request("GET", self.companies_endpoint)
        try:
            text = response.content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ProviderSchemaError("Fund-company catalog is not UTF-8 JavaScript") from error
        match = COMPANY_DOCUMENT.fullmatch(text)
        if match is None:
            raise ProviderSchemaError("Fund-company catalog wrapper changed")
        try:
            rows = json.loads(match.group(1))
        except json.JSONDecodeError as error:
            raise ProviderSchemaError("Fund-company catalog contains invalid JSON") from error
        if not isinstance(rows, list):
            raise ProviderSchemaError("Fund-company catalog must contain an array")
        companies: dict[str, FundCompanyChoice] = {}
        for raw in rows:
            if not isinstance(raw, dict):
                raise ProviderSchemaError("Fund-company catalog row must be an object")
            code = str(raw.get("COMPANYCODE", "")).strip()
            name = str(raw.get("SNAME", "")).strip()
            search_field = str(raw.get("SEARCHFIELD", ""))
            if not COMPANY_CODE.fullmatch(code) or not name:
                raise ProviderSchemaError("Fund-company catalog row is missing code or name")
            if "基金管理" in search_field or name.endswith("基金"):
                companies[code] = FundCompanyChoice(code, name)
        if not companies:
            raise ProviderSchemaError("Fund-company catalog contains no fund managers")
        return tuple(
            sorted(companies.values(), key=lambda item: (item.company_name, item.company_code))
        )

    def discover_company(self, company_code: str) -> FundCatalogSnapshot:
        if not COMPANY_CODE.fullmatch(company_code):
            raise ValueError("company_code must contain exactly eight digits")
        companies = {item.company_code: item for item in self.companies()}
        company = companies.get(company_code)
        if company is None:
            raise ValueError("company_code is not present in the current public catalog")
        url = self.company_endpoint.format(company_code=company_code)
        response = self.http.request("GET", url)
        try:
            text = response.content.decode(response.encoding or "utf-8")
        except UnicodeDecodeError as error:
            raise ProviderSchemaError("Fund-company page cannot be decoded") from error
        parser = _CompanyFundParser()
        parser.feed(text)
        candidates = tuple(
            _candidate(
                fund_code=code,
                fund_name=name,
                manager_code=company.company_code,
                manager_name=company.company_name,
                category=category,
                source_url=str(response.url),
            )
            for code, name, category in parser.rows
            if category.upper().startswith("QDII")
        )
        if not parser.rows:
            raise ProviderSchemaError("Fund-company page contains no recognizable fund rows")
        return FundCatalogSnapshot(
            candidates=candidates,
            raw_payload=response.content,
            source_url=str(response.url),
            mime_type=response.headers.get("content-type", "text/html").split(";", 1)[0],
        )

    def discover_public(self, source_category: str | None = None) -> FundCatalogSnapshot:
        category = source_category or "ALL"
        if category not in SOURCE_CATEGORY_LABELS:
            raise ValueError("source_category is not present in the public QDII taxonomy")
        params: dict[str, str] = {
            "t": "10",
            "lx": "7",
            "letter": "",
            "gsid": "",
            "text": "",
            "sort": "rzdf,desc",
            "atfc": "",
            "onlySale": "0",
            "isLatest": "0",
        }
        if category != "ALL":
            params["feature"] = category
        rows: list[Any] = []
        payloads: list[bytes] = []
        source_url = ""
        mime_type = "text/javascript"
        expected_record: int | None = None
        expected_pages = 1
        page_number = 1
        while page_number <= expected_pages:
            params["page"] = f"{page_number},{PUBLIC_CATALOG_PAGE_SIZE}"
            response = self.http.request("GET", self.public_catalog_endpoint, params=params)
            if not source_url:
                source_url = str(response.url)
                mime_type = response.headers.get(
                    "content-type", "text/javascript"
                ).split(";", 1)[0]
            payloads.append(response.content)
            try:
                text = response.content.decode(response.encoding or "utf-8-sig")
            except UnicodeDecodeError as error:
                raise ProviderSchemaError("Public QDII catalog cannot be decoded") from error
            match = PUBLIC_CATALOG_DOCUMENT.search(text)
            if match is None:
                raise ProviderSchemaError("Public QDII catalog wrapper changed")
            try:
                page_rows = json.loads(match.group(1))
            except json.JSONDecodeError as error:
                raise ProviderSchemaError(
                    "Public QDII catalog contains invalid JSON rows"
                ) from error
            if not isinstance(page_rows, list):
                raise ProviderSchemaError("Public QDII catalog datas must be an array")
            record_match = PUBLIC_CATALOG_RECORD.search(text)
            if record_match is None:
                raise ProviderSchemaError("Public QDII catalog is missing record count")
            page_record = int(record_match.group(1))
            if expected_record is None:
                expected_record = page_record
                expected_pages = max(
                    1,
                    (expected_record + PUBLIC_CATALOG_PAGE_SIZE - 1)
                    // PUBLIC_CATALOG_PAGE_SIZE,
                )
                if expected_pages > PUBLIC_CATALOG_MAX_PAGES:
                    raise ProviderSchemaError("Public QDII catalog exceeds the bounded page limit")
            elif page_record != expected_record:
                raise ProviderSchemaError("Public QDII catalog record count changed between pages")
            rows.extend(page_rows)
            page_number += 1
        candidates: dict[str, PublicFundCandidate] = {}
        for raw in rows:
            if not isinstance(raw, list) or len(raw) < 2:
                raise ProviderSchemaError("Public QDII catalog row is missing code or name")
            code = str(raw[0]).strip()
            name = str(raw[1]).strip()
            if not FUND_CODE.fullmatch(code) or not name:
                raise ProviderSchemaError("Public QDII catalog row has invalid code or name")
            candidates[code] = _candidate(
                fund_code=code,
                fund_name=name,
                manager_code=None,
                manager_name=None,
                category=(
                    SOURCE_CATEGORY_LABELS[category]
                    if category != "ALL"
                    else "QDII（来源未细分）"
                ),
                source_url=source_url,
            )
        if not candidates:
            raise ProviderSchemaError("Public QDII catalog contains no recognizable fund rows")
        if expected_record is None or len(rows) < expected_record:
            raise ProviderSchemaError("Public QDII catalog response is incomplete")
        return FundCatalogSnapshot(
            candidates=tuple(candidates.values()),
            raw_payload=b"\n".join(payloads),
            source_url=source_url,
            mime_type=mime_type,
        )

    def lookup(self, fund_code: str) -> FundCatalogSnapshot:
        if not FUND_CODE.fullmatch(fund_code):
            raise ValueError("fund_code must contain exactly six digits")
        response = self.http.request(
            "GET",
            self.search_endpoint,
            params={"m": "1", "key": fund_code},
        )
        try:
            document = json.loads(response.content)
        except json.JSONDecodeError as error:
            raise ProviderSchemaError("Fund-search response is not JSON") from error
        if not isinstance(document, dict) or document.get("ErrCode") != 0:
            raise ProviderSchemaError("Fund-search response has an invalid status")
        rows = document.get("Datas")
        if not isinstance(rows, list):
            raise ProviderSchemaError("Fund-search response is missing Datas")
        exact = next(
            (row for row in rows if isinstance(row, dict) and str(row.get("CODE")) == fund_code),
            None,
        )
        if exact is None or not isinstance(exact.get("FundBaseInfo"), dict):
            raise ValueError(f"public fund metadata was not found for {fund_code}")
        base = exact["FundBaseInfo"]
        name = _required_text(base, "SHORTNAME")
        manager_code = _required_text(base, "JJGSID")
        manager_name = _required_text(base, "JJGS")
        category = _required_text(base, "FTYPE")
        if not category.upper().startswith("QDII"):
            raise ValueError(f"fund {fund_code} is not classified as QDII by the public source")
        candidate = _candidate(
            fund_code=fund_code,
            fund_name=name,
            manager_code=manager_code,
            manager_name=manager_name,
            category=category,
            source_url=str(response.url),
        )
        return FundCatalogSnapshot(
            candidates=(candidate,),
            raw_payload=response.content,
            source_url=str(response.url),
            mime_type=response.headers.get("content-type", "application/json").split(";", 1)[0],
        )


class _CompanyFundParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str, str]] = []
        self._in_row = False
        self._in_cell = False
        self._cells: list[str] = []
        self._cell_text: list[str] = []
        self._code: str | None = None
        self._name: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "tr":
            self._in_row = True
            self._cells = []
            self._code = None
            self._name = None
        elif tag == "td" and self._in_row:
            self._in_cell = True
            self._cell_text = []
        elif tag == "a" and self._in_row:
            if "code" in classes:
                href = attributes.get("href") or ""
                code_match = re.search(r"([0-9]{6})\.html", href)
                self._code = code_match.group(1) if code_match else None
            elif "name" in classes:
                self._name = (attributes.get("title") or "").strip() or None

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_cell:
            self._cells.append(" ".join("".join(self._cell_text).split()))
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._code and self._name and len(self._cells) >= 3 and self._cells[2]:
                self.rows.append((self._code, self._name, self._cells[2]))
            self._in_row = False


def _required_text(document: dict[str, Any], field: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProviderSchemaError(f"Fund-search response is missing {field}")
    return value.strip()


def _candidate(
    *,
    fund_code: str,
    fund_name: str,
    manager_code: str | None,
    manager_name: str | None,
    category: str,
    source_url: str,
) -> PublicFundCandidate:
    return PublicFundCandidate(
        fund_code=fund_code,
        fund_name=fund_name,
        manager_code=manager_code,
        manager_name=manager_name,
        category=category,
        research_scope=_research_scope(fund_name, category),
        currency=_currency(fund_name),
        wrapper_type=_wrapper(fund_name, category),
        source_url=source_url,
    )


def _research_scope(name: str, category: str) -> str:
    text = f"{name} {category}".upper()
    technology_terms = ("科技", "芯片", "半导体", "互联网", "数字经济", "人工智能", "AI")
    if any(word in text for word in technology_terms):
        return "TECHNOLOGY"
    if any(word in text for word in ("商品", "原油", "黄金", "白银", "有色")):
        return "COMMODITY"
    if any(word in text for word in ("房地产", "REIT")):
        return "REAL_ESTATE"
    if "债" in text:
        return "FIXED_INCOME"
    if any(word in text for word in ("股票", "混合", "指数", "ETF")):
        return "EQUITY"
    return "OTHER"


def _currency(name: str) -> str:
    if "美元" in name:
        return "USD"
    if "港币" in name or "港元" in name:
        return "HKD"
    return "CNY"


def _wrapper(name: str, category: str) -> str:
    text = f"{name} {category}".upper()
    if "ETF联接" in text or "指数联接" in text:
        return "ETF_FEEDER"
    if "FOF" in text or "基金中基金" in text:
        return "FOF"
    if "ETF" in text:
        return "ETF"
    if "LOF" in text:
        return "LOF"
    return "DIRECT"
