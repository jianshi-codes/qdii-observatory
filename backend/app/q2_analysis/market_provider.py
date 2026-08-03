"""Validated, cached, provider-neutral market and FX series."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.app.ingestion.http import ProviderHttpClient
from backend.app.ingestion.providers.base import ProviderSchemaError
from backend.app.q2_analysis import ANALYSIS_START_DATE

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_ROOT: Final = REPOSITORY_ROOT / ".data" / "analysis-cache"
SYMBOL_PATTERN: Final = re.compile(r"^[A-Z0-9^][A-Z0-9.^=-]*$")


@dataclass(frozen=True, slots=True)
class MarketPoint:
    trade_date: date
    adjusted_close: Decimal


@dataclass(frozen=True, slots=True)
class MarketSeries:
    symbol: str
    currency: str
    exchange: str
    timezone: str
    points: tuple[MarketPoint, ...]
    source_provider: str
    source_url: str
    fetched_at: datetime
    from_cache: bool
    cache_path: Path | None


class YahooChartMarketProvider:
    """Yahoo chart adapter; no upstream JSON field escapes this module."""

    name = "YAHOO_CHART"
    version = "v8-chart-adjusted-close-v1"
    endpoint = "https://query2.finance.yahoo.com/v8/finance/chart"

    def __init__(
        self,
        http: ProviderHttpClient,
        *,
        cache_root: Path = DEFAULT_CACHE_ROOT,
    ) -> None:
        self.http = http
        self.cache_root = cache_root

    def fetch_series(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        *,
        refresh: bool = False,
        no_cache: bool = False,
    ) -> MarketSeries:
        _validate_dates(start_date, end_date)
        normalized_symbol = symbol.strip().upper()
        if not SYMBOL_PATTERN.fullmatch(normalized_symbol):
            raise ValueError(f"Invalid provider symbol: {symbol!r}")
        cache_path = self._cache_path(normalized_symbol, start_date, end_date)
        metadata_path = cache_path.with_suffix(".meta.json")
        if (
            not no_cache
            and not refresh
            and cache_path.is_file()
            and metadata_path.is_file()
        ):
            raw = cache_path.read_bytes()
            cache_metadata = _read_cache_metadata(
                metadata_path,
                raw=raw,
                symbol=normalized_symbol,
                start_date=start_date,
                end_date=end_date,
            )
            fetched_at = datetime.fromisoformat(cache_metadata["fetched_at"])
            return _parse_chart_response(
                raw,
                requested_symbol=normalized_symbol,
                start_date=start_date,
                end_date=end_date,
                source_url=cache_metadata["source_url"],
                fetched_at=fetched_at,
                from_cache=True,
                cache_path=cache_path,
            )

        response = self.http.request(
            "GET",
            f"{self.endpoint}/{quote(normalized_symbol, safe='')}",
            params=_query_params(start_date, end_date),
            headers={
                "Accept": "application/json, text/plain, */*",
                "User-Agent": "Mozilla/5.0 QDII-Tech-Fund-Observatory/0.1",
            },
        )
        raw = response.content
        fetched_at = datetime.now(UTC)
        result = _parse_chart_response(
            raw,
            requested_symbol=normalized_symbol,
            start_date=start_date,
            end_date=end_date,
            source_url=str(response.url),
            fetched_at=fetched_at,
            from_cache=False,
            cache_path=None if no_cache else cache_path,
        )
        if not no_cache:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_bytes = json.dumps(
                {
                    "provider": self.name,
                    "provider_version": self.version,
                    "symbol": normalized_symbol,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "fetched_at": fetched_at.isoformat(),
                    "source_url": str(response.url),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
            _atomic_write(cache_path, raw)
            _atomic_write(metadata_path, metadata_bytes)
        return result

    def fetch_fx_series(
        self,
        base_currency: str,
        quote_currency: str,
        start_date: date,
        end_date: date,
        *,
        refresh: bool = False,
        no_cache: bool = False,
    ) -> MarketSeries | None:
        base = _currency(base_currency)
        target = _currency(quote_currency)
        if base == target:
            return None
        return self.fetch_series(
            f"{base}{target}=X",
            start_date,
            end_date,
            refresh=refresh,
            no_cache=no_cache,
        )

    def _cache_path(self, symbol: str, start_date: date, end_date: date) -> Path:
        readable = re.sub(r"[^A-Z0-9.-]+", "_", symbol).strip("_") or "symbol"
        digest = hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:10]
        return (
            self.cache_root
            / "market"
            / self.name.lower()
            / self.version
            / f"{readable}-{digest}"
            / f"{start_date.isoformat()}_{end_date.isoformat()}.json"
        )

def _query_params(start_date: date, end_date: date) -> dict[str, str]:
    period1 = int(datetime.combine(start_date, time.min, tzinfo=UTC).timestamp())
    period2 = int(
        datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC).timestamp()
    )
    return {
        "period1": str(period1),
        "period2": str(period2),
        "interval": "1d",
        "events": "div,splits",
    }


def _parse_chart_response(
    raw: bytes,
    *,
    requested_symbol: str,
    start_date: date,
    end_date: date,
    source_url: str,
    fetched_at: datetime,
    from_cache: bool,
    cache_path: Path | None,
) -> MarketSeries:
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ProviderSchemaError("Yahoo chart response is not valid JSON") from error
    if not isinstance(document, dict) or not isinstance(document.get("chart"), dict):
        raise ProviderSchemaError("Yahoo chart response is missing chart")
    chart = document["chart"]
    error_document = chart.get("error")
    if error_document is not None:
        raise ProviderSchemaError(f"Yahoo chart returned an error: {error_document!r}")
    result = chart.get("result")
    if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
        raise ProviderSchemaError("Yahoo chart response must contain exactly one result")
    payload = result[0]
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        raise ProviderSchemaError("Yahoo chart result is missing meta")
    response_symbol = _required_text(meta, "symbol").upper()
    if response_symbol != requested_symbol:
        raise ProviderSchemaError(
            f"Yahoo chart symbol mismatch: requested {requested_symbol}, got {response_symbol}"
        )
    currency = _required_text(meta, "currency")
    exchange = _required_text(meta, "exchangeName")
    timezone_name = _required_text(meta, "exchangeTimezoneName")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ProviderSchemaError(f"Unknown exchange timezone: {timezone_name}") from error
    timestamps = payload.get("timestamp")
    indicators = payload.get("indicators")
    if not isinstance(timestamps, list) or not isinstance(indicators, dict):
        raise ProviderSchemaError("Yahoo chart result is missing timestamps or indicators")
    adjusted_documents = indicators.get("adjclose")
    if (
        not isinstance(adjusted_documents, list)
        or len(adjusted_documents) != 1
        or not isinstance(adjusted_documents[0], dict)
        or not isinstance(adjusted_documents[0].get("adjclose"), list)
    ):
        raise ProviderSchemaError("Yahoo chart result is missing adjusted close values")
    values = adjusted_documents[0]["adjclose"]
    if len(timestamps) != len(values):
        raise ProviderSchemaError("Yahoo chart timestamps and adjusted closes differ in length")

    points: list[MarketPoint] = []
    seen_dates: set[date] = set()
    for index, (timestamp, value) in enumerate(zip(timestamps, values, strict=True)):
        if not isinstance(timestamp, int):
            raise ProviderSchemaError(f"Yahoo chart timestamp[{index}] is not an integer")
        trade_date = datetime.fromtimestamp(timestamp, tz=UTC).astimezone(timezone).date()
        if trade_date < start_date or trade_date > end_date or value is None:
            continue
        adjusted_close = _positive_decimal(value, f"adjclose[{index}]")
        if trade_date in seen_dates:
            raise ProviderSchemaError(f"Yahoo chart contains duplicate date {trade_date}")
        seen_dates.add(trade_date)
        points.append(MarketPoint(trade_date=trade_date, adjusted_close=adjusted_close))
    points.sort(key=lambda item: item.trade_date)
    if not points:
        raise ProviderSchemaError(
            f"Yahoo chart returned no usable rows for {requested_symbol} in requested range"
        )
    return MarketSeries(
        symbol=response_symbol,
        currency=currency,
        exchange=exchange,
        timezone=timezone_name,
        points=tuple(points),
        source_provider=YahooChartMarketProvider.name,
        source_url=source_url,
        fetched_at=fetched_at,
        from_cache=from_cache,
        cache_path=cache_path,
    )


def _read_cache_metadata(
    path: Path,
    *,
    raw: bytes,
    symbol: str,
    start_date: date,
    end_date: date,
) -> dict[str, str]:
    try:
        document = json.loads(path.read_bytes())
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ProviderSchemaError("Market cache metadata is not valid JSON") from error
    expected = {
        "provider": YahooChartMarketProvider.name,
        "provider_version": YahooChartMarketProvider.version,
        "symbol": symbol,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if not isinstance(document, dict) or any(
        document.get(key) != value for key, value in expected.items()
    ):
        raise ProviderSchemaError("Market cache metadata does not match the cached response")
    fetched_at = document.get("fetched_at")
    source_url = document.get("source_url")
    if not isinstance(fetched_at, str) or not isinstance(source_url, str):
        raise ProviderSchemaError("Market cache metadata lacks fetched_at or source_url")
    try:
        parsed_at = datetime.fromisoformat(fetched_at)
    except ValueError as error:
        raise ProviderSchemaError("Market cache fetched_at is invalid") from error
    if parsed_at.tzinfo is None:
        raise ProviderSchemaError("Market cache fetched_at must be timezone-aware")
    return {"fetched_at": fetched_at, "source_url": source_url}


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _validate_dates(start_date: date, end_date: date) -> None:
    if start_date < ANALYSIS_START_DATE:
        raise ValueError(
            f"Market history start_date must not precede {ANALYSIS_START_DATE.isoformat()}"
        )
    if end_date < start_date:
        raise ValueError("Market history end_date must be on or after start_date")


def _required_text(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProviderSchemaError(f"Yahoo chart meta.{key} must be non-empty text")
    return value.strip()


def _positive_decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ProviderSchemaError(f"Yahoo chart {field} is not numeric") from error
    if not result.is_finite() or result <= 0:
        raise ProviderSchemaError(f"Yahoo chart {field} must be positive and finite")
    return result


def _currency(value: str) -> str:
    normalized = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", normalized):
        raise ValueError(f"Invalid currency: {value!r}")
    return normalized
