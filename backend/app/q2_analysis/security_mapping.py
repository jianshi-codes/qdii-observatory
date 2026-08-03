"""Small-scope mapping from disclosed security identifiers to market symbols."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from backend.app.models import ReportSecurityHolding

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
DEFAULT_MAPPING_PATH: Final = REPOSITORY_ROOT / "config" / "analysis-security-map.yaml"
SYMBOL_PATTERN: Final = re.compile(r"^[A-Z0-9^][A-Z0-9.^=-]*$")
CANONICAL_MARKETS: Final = frozenset({"US", "HK", "KR", "JP", "CN_SH", "CN_SZ", "UK"})
CODE_SUFFIX_MARKETS: Final = {"US": "US", "JP": "JP", "KS": "KR", "HK": "HK"}


@dataclass(frozen=True, slots=True)
class ManualSecurityMapping:
    security_code_raw: str
    market: str | None
    symbol: str
    currency: str
    reason: str


@dataclass(frozen=True, slots=True)
class SecurityMapping:
    provider_symbol: str | None
    currency: str | None
    market: str | None
    source: str
    reason: str

    @property
    def is_mapped(self) -> bool:
        return self.provider_symbol is not None and self.currency is not None


@lru_cache(maxsize=8)
def load_manual_mappings(path: Path = DEFAULT_MAPPING_PATH) -> tuple[ManualSecurityMapping, ...]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("Security mapping config must have version: 1")
    rows = document.get("mappings")
    if not isinstance(rows, list):
        raise ValueError("Security mapping config must contain a mappings list")
    result: list[ManualSecurityMapping] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict) or not isinstance(raw.get("match"), dict):
            raise ValueError(f"mappings[{index}] must contain a match object")
        match = raw["match"]
        code = _required_text(match, "security_code_raw").upper()
        market = _optional_text(match.get("market"))
        symbol = _required_text(raw, "symbol").upper()
        currency = _currency(_required_text(raw, "currency"))
        reason = _required_text(raw, "reason")
        if not SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError(f"mappings[{index}].symbol is invalid: {symbol}")
        result.append(
            ManualSecurityMapping(
                security_code_raw=code,
                market=_canonical_market(market),
                symbol=symbol,
                currency=currency,
                reason=reason,
            )
        )
    return tuple(result)


def map_security_holding(
    holding: ReportSecurityHolding,
    *,
    manual_mappings: tuple[ManualSecurityMapping, ...] | None = None,
) -> SecurityMapping:
    code = (holding.security_code_raw or "").strip().upper()
    market = _canonical_market(holding.market_normalized or holding.exchange_raw)
    suffix_market = _market_from_code_suffix(code)
    if (
        suffix_market is not None
        and market in CANONICAL_MARKETS
        and market != suffix_market
    ):
        return SecurityMapping(
            provider_symbol=None,
            currency=_optional_currency(holding.currency) or _currency_for_market(market),
            market=market,
            source="UNRESOLVED",
            reason=f"证券代码市场后缀 {suffix_market} 与披露市场 {market} 冲突",
        )
    if suffix_market is not None:
        market = suffix_market
    currency = _optional_currency(holding.currency) or _currency_for_market(market)
    mappings = manual_mappings if manual_mappings is not None else load_manual_mappings()

    for item in mappings:
        if item.security_code_raw != code:
            continue
        if item.market is not None and item.market != market:
            continue
        return SecurityMapping(
            provider_symbol=item.symbol,
            currency=item.currency,
            market=market,
            source="MANUAL_CONFIG",
            reason=item.reason,
        )

    symbol = _deterministic_symbol(code, market)
    if symbol is None:
        reason = "缺少可验证的证券代码" if not code else f"无法按市场规则映射代码 {code}"
        return SecurityMapping(
            provider_symbol=None,
            currency=currency,
            market=market,
            source="UNRESOLVED",
            reason=reason,
        )
    if currency is None:
        return SecurityMapping(
            provider_symbol=None,
            currency=None,
            market=market,
            source="UNRESOLVED",
            reason=f"已识别行情代码 {symbol}，但证券币种无法确定",
        )
    return SecurityMapping(
        provider_symbol=symbol,
        currency=currency,
        market=market,
        source="DETERMINISTIC_RULE",
        reason=f"由披露代码和 {market or '未知市场'} 的固定规则映射",
    )


def _deterministic_symbol(code: str, market: str | None) -> str | None:
    if not code:
        return None
    suffix_match = re.fullmatch(r"([A-Z0-9.-]+)\s+(US|JP|KS|HK)", code)
    base = suffix_match.group(1) if suffix_match else code

    if market == "US" and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", base):
        return base
    if market == "JP" and re.fullmatch(r"[0-9A-Z]{4,5}", base):
        return f"{base}.T"
    if market == "KR" and re.fullmatch(r"\d{6}", base):
        return f"{base}.KS"
    if market == "HK" and re.fullmatch(r"\d{1,5}", base):
        return f"{base.zfill(4)}.HK"
    if market == "CN_SH" and re.fullmatch(r"\d{6}", base):
        return f"{base}.SS"
    if market == "CN_SZ" and re.fullmatch(r"\d{6}", base):
        return f"{base}.SZ"
    if market == "UK" and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", base):
        return f"{base}.L"
    return None


def _canonical_market(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().upper().replace(" ", "")
    if normalized in {"US", "USA", "UNITEDSTATES", "UNITEDSTATESOFAMERICA"} or any(
        token in normalized for token in ("NASDAQ", "NYSE", "美国证券")
    ):
        return "US"
    if any(token in normalized for token in ("HKEX", "香港", "HONGKONG")):
        return "HK"
    if any(token in normalized for token in ("KRX", "韩国", "KOREA")) or normalized == "KR":
        return "KR"
    if (
        any(token in normalized for token in ("东京", "日本", "TOKYO", "JAPAN"))
        or normalized == "JP"
    ):
        return "JP"
    if any(token in normalized for token in ("上海", "SSE", "SHANGHAI")):
        return "CN_SH"
    if any(token in normalized for token in ("深圳", "SZSE", "SHENZHEN")):
        return "CN_SZ"
    if any(token in normalized for token in ("伦敦", "LONDON", "LSE")):
        return "UK"
    return normalized


def _market_from_code_suffix(code: str) -> str | None:
    suffix_match = re.fullmatch(r"[A-Z0-9.-]+\s+(US|JP|KS|HK)", code)
    return CODE_SUFFIX_MARKETS[suffix_match.group(1)] if suffix_match else None


def _currency_for_market(market: str | None) -> str | None:
    if market is None:
        return None
    return {
        "US": "USD",
        "HK": "HKD",
        "KR": "KRW",
        "JP": "JPY",
        "CN_SH": "CNY",
        "CN_SZ": "CNY",
        "UK": "GBP",
    }.get(market)


def _required_text(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_currency(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _currency(value)


def _currency(value: str) -> str:
    currency = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError(f"Invalid currency: {value!r}")
    return currency
