"""Historical official-NAV provider adapters."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.app.ingestion.http import ProviderHttpClient
from backend.app.ingestion.providers.base import NavPage, NavRecord, ProviderSchemaError


class EastmoneyNavProvider:
    """Adapter for Eastmoney's public, undocumented historical NAV endpoint."""

    name = "EASTMONEY_NAV"
    version = "lsjz-v1"
    endpoint = "https://api.fund.eastmoney.com/f10/lsjz"

    def __init__(self, http: ProviderHttpClient) -> None:
        self.http = http

    def fetch_page(
        self,
        share_code: str,
        page_index: int,
        page_size: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> NavPage:
        if page_index < 1 or page_size < 1 or page_size > 1000:
            raise ValueError("Invalid NAV pagination")
        params: dict[str, str | int] = {
            "fundCode": share_code,
            "pageIndex": page_index,
            "pageSize": page_size,
        }
        if start_date is not None:
            params["startDate"] = start_date.isoformat()
        if end_date is not None:
            params["endDate"] = end_date.isoformat()
        response = self.http.request(
            "GET",
            self.endpoint,
            params=params,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": f"https://fundf10.eastmoney.com/jjjz_{share_code}.html",
            },
        )
        payload = response.content
        try:
            document = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ProviderSchemaError("Eastmoney NAV response is not JSON") from error
        records, total, returned_page_size, returned_page = _parse_nav_document(document)
        if returned_page != page_index:
            raise ProviderSchemaError(
                f"NAV page mismatch: requested {page_index}, received {returned_page}"
            )
        total_pages = math.ceil(total / returned_page_size) if total else 0
        return NavPage(
            provider_name=self.name,
            provider_version=self.version,
            share_code=share_code,
            page_index=returned_page,
            total_pages=total_pages,
            total_records=total,
            records=tuple(records),
            raw_payload=payload,
            source_url=str(response.url),
            mime_type=response.headers.get("content-type", "application/json").split(";", 1)[0],
        )


def _parse_decimal(value: Any, field: str, *, optional: bool = False) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if optional:
            return None
        raise ProviderSchemaError(f"NAV field {field} is empty")
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError) as error:
        raise ProviderSchemaError(f"NAV field {field} is not decimal: {value!r}") from error


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    for parser in (datetime.fromisoformat,):
        try:
            parsed = parser(text)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ProviderSchemaError(f"Invalid source publication timestamp: {value!r}")


def _parse_nav_document(document: Any) -> tuple[list[NavRecord], int, int, int]:
    if not isinstance(document, dict):
        raise ProviderSchemaError("NAV top-level response must be an object")
    if document.get("ErrCode") != 0:
        raise ProviderSchemaError(
            "NAV provider error: "
            f"code={document.get('ErrCode')!r}, message={document.get('ErrMsg')!r}"
        )
    data = document.get("Data")
    if not isinstance(data, dict) or not isinstance(data.get("LSJZList"), list):
        raise ProviderSchemaError("NAV response is missing Data.LSJZList")
    try:
        total = int(document["TotalCount"])
        page_size = int(document["PageSize"])
        page_index = int(document["PageIndex"])
    except (KeyError, TypeError, ValueError) as error:
        raise ProviderSchemaError("NAV response has invalid pagination fields") from error
    rows: list[NavRecord] = []
    for raw in data["LSJZList"]:
        if not isinstance(raw, dict):
            raise ProviderSchemaError("NAV row must be an object")
        try:
            nav_date = date.fromisoformat(str(raw["FSRQ"]))
        except (KeyError, ValueError) as error:
            raise ProviderSchemaError(f"Invalid NAV date row: {raw!r}") from error
        unit_nav = _parse_decimal(raw.get("DWJZ"), "DWJZ")
        if unit_nav is None or unit_nav <= 0:
            raise ProviderSchemaError(f"NAV unit value must be positive: {raw.get('DWJZ')!r}")
        rows.append(
            NavRecord(
                nav_date=nav_date,
                unit_nav=unit_nav,
                accumulated_nav=_parse_decimal(raw.get("LJJZ"), "LJJZ", optional=True),
                published_daily_return_pct=_parse_decimal(raw.get("JZZZL"), "JZZZL", optional=True),
                source_published_at=_parse_timestamp(raw.get("SDATE")),
            )
        )
    if total > 0 and not rows:
        raise ProviderSchemaError("NAV provider returned an empty page for a non-empty result")
    return rows, total, page_size, page_index


class EastmoneyChartNavProvider:
    """Full-history adapter for the JavaScript dataset used by Eastmoney fund pages."""

    name = "EASTMONEY_NAV_CHART"
    version = "pingzhongdata-v1"
    endpoint_template = "https://fund.eastmoney.com/pingzhongdata/{share_code}.js"

    def __init__(self, http: ProviderHttpClient) -> None:
        self.http = http

    def fetch_page(
        self,
        share_code: str,
        page_index: int,
        page_size: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> NavPage:
        if len(share_code) != 6 or not share_code.isdigit():
            raise ValueError(f"Invalid fund share code: {share_code!r}")
        if page_index != 1:
            raise ValueError("Chart NAV provider has exactly one source page")
        if page_size < 1:
            raise ValueError("Invalid NAV page size")
        url = self.endpoint_template.format(share_code=share_code)
        response = self.http.request(
            "GET",
            url,
            headers={
                "Accept": "application/javascript, text/javascript, */*",
                "Referer": f"https://fund.eastmoney.com/{share_code}.html",
            },
        )
        records = _parse_chart_document(
            response.content,
            share_code,
            start_date=start_date,
            end_date=end_date,
        )
        return NavPage(
            provider_name=self.name,
            provider_version=self.version,
            share_code=share_code,
            page_index=1,
            total_pages=1,
            total_records=len(records),
            records=tuple(records),
            raw_payload=response.content,
            source_url=str(response.url),
            mime_type=response.headers.get("content-type", "application/javascript").split(";", 1)[
                0
            ],
        )


def _parse_chart_document(
    payload: bytes,
    share_code: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[NavRecord]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ProviderSchemaError("Chart NAV response is not UTF-8 JavaScript") from error
    code_match = re.search(r'var\s+fS_code\s*=\s*"([0-9]{6})"\s*;', text)
    if code_match is None or code_match.group(1) != share_code:
        raise ProviderSchemaError("Chart NAV response code does not match the requested share")
    net_rows = _chart_json_array(text, "Data_netWorthTrend")
    accumulated_rows = _chart_json_array(text, "Data_ACWorthTrend")
    if not net_rows:
        raise ProviderSchemaError("Chart NAV response contains no unit-NAV rows")
    accumulated_by_date: dict[date, Decimal] = {}
    accumulated_dates: set[date] = set()
    for raw in accumulated_rows:
        if not isinstance(raw, list) or len(raw) < 2:
            raise ProviderSchemaError("Chart accumulated-NAV row must be a two-item array")
        nav_date = _chart_date(raw[0])
        if nav_date in accumulated_dates:
            raise ProviderSchemaError(f"Chart accumulated NAV contains duplicate date {nav_date}")
        accumulated_dates.add(nav_date)
        value = _parse_decimal(raw[1], "Data_ACWorthTrend.y", optional=True)
        if value is None:
            continue
        if value <= 0:
            raise ProviderSchemaError("Chart accumulated NAV must be positive")
        accumulated_by_date[nav_date] = value

    records: list[NavRecord] = []
    seen_dates: set[date] = set()
    for raw in net_rows:
        if not isinstance(raw, dict) or "x" not in raw or "y" not in raw:
            raise ProviderSchemaError("Chart unit-NAV row must contain x and y")
        nav_date = _chart_date(raw["x"])
        if nav_date in seen_dates:
            raise ProviderSchemaError(f"Chart NAV contains duplicate date {nav_date}")
        seen_dates.add(nav_date)
        if start_date is not None and nav_date < start_date:
            continue
        if end_date is not None and nav_date > end_date:
            continue
        unit_nav = _parse_decimal(raw["y"], "Data_netWorthTrend.y")
        if unit_nav is None or unit_nav <= 0:
            raise ProviderSchemaError("Chart unit NAV must be positive")
        records.append(
            NavRecord(
                nav_date=nav_date,
                unit_nav=unit_nav,
                accumulated_nav=accumulated_by_date.get(nav_date),
                published_daily_return_pct=_parse_decimal(
                    raw.get("equityReturn"),
                    "Data_netWorthTrend.equityReturn",
                    optional=True,
                ),
                source_published_at=None,
            )
        )
    records.sort(key=lambda item: item.nav_date)
    return records


def _chart_json_array(text: str, variable: str) -> list[Any]:
    match = re.search(rf"var\s+{re.escape(variable)}\s*=\s*(\[.*?\])\s*;", text, re.DOTALL)
    if match is None:
        raise ProviderSchemaError(f"Chart NAV response is missing {variable}")
    try:
        value = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise ProviderSchemaError(f"Chart NAV variable {variable} is invalid JSON") from error
    if not isinstance(value, list):
        raise ProviderSchemaError(f"Chart NAV variable {variable} must be an array")
    return value


def _chart_date(value: Any) -> date:
    try:
        timestamp_ms = int(value)
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).date()
    except (TypeError, ValueError, OSError, OverflowError) as error:
        raise ProviderSchemaError(f"Invalid chart NAV timestamp: {value!r}") from error
