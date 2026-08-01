"""End-of-day exchange price provider."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from backend.app.ingestion.http import ProviderHttpClient
from backend.app.ingestion.providers.base import ExchangePriceRecord, ProviderSchemaError


class EastmoneyMarketPriceProvider:
    name = "EASTMONEY_MARKET"
    version = "push2his-kline-v1"
    endpoint = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def __init__(self, http: ProviderHttpClient) -> None:
        self.http = http

    def fetch(
        self, share_code: str, start_date: date, end_date: date
    ) -> tuple[bytes, tuple[ExchangePriceRecord, ...], str]:
        market = _market_prefix(share_code)
        response = self.http.request(
            "GET",
            self.endpoint,
            params={
                "secid": f"{market}.{share_code}",
                "klt": "101",
                "fqt": "0",
                "beg": start_date.strftime("%Y%m%d"),
                "end": end_date.strftime("%Y%m%d"),
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            },
            headers={"Accept": "application/json, text/plain, */*"},
        )
        raw = response.content
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ProviderSchemaError("Market response is not JSON") from error
        records = _parse_market_document(document, share_code)
        return raw, tuple(records), str(response.url)


def _market_prefix(code: str) -> int:
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"Invalid exchange share code: {code!r}")
    if code.startswith(("5", "6", "9")):
        return 1
    if code.startswith(("0", "1", "2", "3")):
        return 0
    raise ValueError(f"Cannot infer exchange for share code: {code}")


def _decimal(value: str, field: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ProviderSchemaError(f"Market field {field} is not decimal: {value!r}") from error


def _parse_market_document(document: Any, share_code: str) -> list[ExchangePriceRecord]:
    if not isinstance(document, dict) or document.get("rc") != 0:
        raise ProviderSchemaError(f"Market provider error response: {document!r}")
    data = document.get("data")
    if data is None:
        return []
    if not isinstance(data, dict) or data.get("code") != share_code:
        raise ProviderSchemaError("Market response code does not match the requested share")
    klines = data.get("klines")
    if not isinstance(klines, list):
        raise ProviderSchemaError("Market response is missing data.klines")
    rows: list[ExchangePriceRecord] = []
    for raw in klines:
        fields = str(raw).split(",")
        if len(fields) < 11:
            raise ProviderSchemaError(f"Market kline has {len(fields)} fields, expected 11")
        try:
            trade_date = date.fromisoformat(fields[0])
        except ValueError as error:
            raise ProviderSchemaError(f"Invalid market date: {fields[0]!r}") from error
        rows.append(
            ExchangePriceRecord(
                trade_date=trade_date,
                open=_decimal(fields[1], "open"),
                close=_decimal(fields[2], "close"),
                high=_decimal(fields[3], "high"),
                low=_decimal(fields[4], "low"),
                volume=_decimal(fields[5], "volume"),
                turnover=_decimal(fields[6], "turnover"),
                pct_change=_decimal(fields[8], "pct_change"),
            )
        )
    return rows
