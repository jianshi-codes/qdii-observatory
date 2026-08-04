"""Transparent Q2 disclosed-holdings return baseline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal

import yaml

from backend.app.q2_analysis import MODEL_NAME

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[3]
PUBLIC_PROXY_PATH: Final = REPOSITORY_ROOT / "config" / "fund-analysis-proxies.yaml"
LOCAL_PROXY_PATH: Final = REPOSITORY_ROOT / "config" / "fund-analysis-proxies.local.yaml"
PCT_SCALE: Final = Decimal("0.00000001")
Confidence = Literal["HIGH", "MEDIUM", "LOW", "LOW_CONFIDENCE"]
AnalysisMode = Literal["Q2_EX_POST", "Q2_LIVE"]


@dataclass(frozen=True, slots=True)
class ProxyDefinition:
    symbol: str
    currency: str
    weight: Decimal


@dataclass(frozen=True, slots=True)
class FundProxyConfig:
    representative_code: str
    proxies: tuple[ProxyDefinition, ...]
    reason: str
    confidence: str


@dataclass(frozen=True, slots=True)
class HoldingReturnInput:
    name: str
    raw_code: str | None
    provider_symbol: str | None
    market: str | None
    currency: str | None
    mapping_source: str
    mapping_reason: str
    weight_pct: Decimal
    trade_date: date | None
    previous_trade_date: date | None
    return_pct: Decimal | None
    alignment_policy: str | None


@dataclass(frozen=True, slots=True)
class ProxyReturnInput:
    symbol: str
    currency: str
    basket_weight: Decimal
    trade_date: date | None
    previous_trade_date: date | None
    return_pct: Decimal | None
    alignment_policy: str


@dataclass(frozen=True, slots=True)
class FundHoldingReturnInput:
    name: str
    raw_code: str | None
    resolved_fund_code: str | None
    weight_pct: Decimal
    nav_date: date | None
    return_pct: Decimal | None
    is_unresolved: bool


@dataclass(frozen=True, slots=True)
class Contribution:
    name: str
    symbol: str | None
    weight_pct: Decimal
    return_pct: Decimal | None
    contribution_pct: Decimal | None
    trade_date: date | None
    previous_trade_date: date | None
    source: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class PredictionCoverage:
    disclosed_security_weight_pct: Decimal
    mapped_security_weight_pct: Decimal
    priced_security_weight_pct: Decimal
    unresolved_security_weight_pct: Decimal
    missing_market_data_weight_pct: Decimal
    undisclosed_equity_weight_pct: Decimal
    proxy_weight_pct: Decimal
    fund_holding_weight_pct: Decimal
    resolved_fund_holding_weight_pct: Decimal
    unresolved_fund_weight_pct: Decimal
    cash_weight_pct: Decimal
    total_explained_weight_pct: Decimal


@dataclass(frozen=True, slots=True)
class DailyPrediction:
    nav_date: date
    actual_return_pct: Decimal | None
    actual_return_source: str | None
    predicted_return_pct: Decimal | None
    lower_bound_pct: Decimal | None
    upper_bound_pct: Decimal | None
    known_contribution_pct: Decimal | None
    proxy_contribution_pct: Decimal | None
    fund_holding_contribution_pct: Decimal | None
    cash_contribution_pct: Decimal
    residual_pct: Decimal | None
    analysis_mode: AnalysisMode
    confidence: Confidence
    coverage: PredictionCoverage
    security_contributions: tuple[Contribution, ...]
    proxy_contributions: tuple[Contribution, ...]
    fund_holding_contributions: tuple[Contribution, ...]
    model: str = MODEL_NAME

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def predict_day(
    *,
    nav_date: date,
    actual_return_pct: Decimal | None,
    actual_return_source: str | None,
    report_public_available_at: datetime,
    holdings: tuple[HoldingReturnInput, ...],
    equity_nav_pct: Decimal,
    fund_holdings: tuple[FundHoldingReturnInput, ...],
    cash_weight_pct: Decimal,
    proxy_config: FundProxyConfig | None,
    proxy_returns: tuple[ProxyReturnInput, ...],
    prior_residuals: tuple[Decimal, ...] = (),
) -> DailyPrediction:
    _validate_weight("equity_nav_pct", equity_nav_pct)
    _validate_weight("cash_weight_pct", cash_weight_pct)
    for item in holdings:
        _validate_weight(f"security {item.name}", item.weight_pct)
    for fund_item in fund_holdings:
        _validate_weight(f"fund holding {fund_item.name}", fund_item.weight_pct)
    security_items = tuple(_security_contribution(item) for item in holdings)
    disclosed_weight = _sum(item.weight_pct for item in holdings)
    mapped_weight = _sum(
        item.weight_pct for item in holdings if item.provider_symbol is not None
    )
    priced_weight = _sum(
        item.weight_pct for item in holdings if item.return_pct is not None
    )
    unresolved_security_weight = max(Decimal("0"), disclosed_weight - mapped_weight)
    missing_market_weight = max(Decimal("0"), mapped_weight - priced_weight)
    if disclosed_weight > equity_nav_pct + Decimal("0.05"):
        raise ValueError(
            "Disclosed security weight exceeds reported equity_nav_pct by more than "
            "the 0.05 percentage-point rounding tolerance"
        )
    undisclosed_equity_weight = max(Decimal("0"), equity_nav_pct - disclosed_weight)
    known_contribution = _sum_optional(item.contribution_pct for item in security_items)

    proxy_items: tuple[Contribution, ...] = ()
    configured_proxy_weight = Decimal("0")
    priced_proxy_weight = Decimal("0")
    if proxy_config is not None:
        by_symbol = {item.symbol: item for item in proxy_returns}
        built: list[Contribution] = []
        configured_proxy_weight = undisclosed_equity_weight
        for definition in proxy_config.proxies:
            proxy_return = by_symbol.get(definition.symbol)
            allocated_weight = undisclosed_equity_weight * definition.weight
            if proxy_return is not None and proxy_return.return_pct is not None:
                priced_proxy_weight += allocated_weight
            built.append(
                Contribution(
                    name=definition.symbol,
                    symbol=definition.symbol,
                    weight_pct=_q(allocated_weight),
                    return_pct=(
                        _q(proxy_return.return_pct)
                        if proxy_return is not None and proxy_return.return_pct is not None
                        else None
                    ),
                    contribution_pct=(
                        _contribution(allocated_weight, proxy_return.return_pct)
                        if proxy_return is not None and proxy_return.return_pct is not None
                        else None
                    ),
                    trade_date=proxy_return.trade_date if proxy_return else None,
                    previous_trade_date=(
                        proxy_return.previous_trade_date if proxy_return else None
                    ),
                    source="UNDISCLOSED_EQUITY_PROXY",
                    note=proxy_config.reason,
                )
            )
        proxy_items = tuple(built)
    proxy_contribution = _sum_optional(item.contribution_pct for item in proxy_items)

    fund_items = tuple(_fund_holding_contribution(item) for item in fund_holdings)
    fund_weight = _sum(item.weight_pct for item in fund_holdings)
    if equity_nav_pct + fund_weight + cash_weight_pct > Decimal("100.05"):
        raise ValueError("Reported equity, fund, and cash weights exceed 100%")
    resolved_fund_weight = _sum(
        item.weight_pct
        for item in fund_holdings
        if not item.is_unresolved and item.return_pct is not None
    )
    unresolved_fund_weight = _sum(
        item.weight_pct
        for item in fund_holdings
        if item.is_unresolved or item.return_pct is None
    )
    fund_contribution = _sum_optional(item.contribution_pct for item in fund_items)
    total_explained = (
        priced_weight + priced_proxy_weight + resolved_fund_weight + cash_weight_pct
    )
    if total_explained > Decimal("100.05"):
        raise ValueError("Total explained weight exceeds 100% beyond rounding tolerance")
    total_explained = min(Decimal("100"), total_explained)
    coverage = PredictionCoverage(
        disclosed_security_weight_pct=_q(disclosed_weight),
        mapped_security_weight_pct=_q(mapped_weight),
        priced_security_weight_pct=_q(priced_weight),
        unresolved_security_weight_pct=_q(unresolved_security_weight),
        missing_market_data_weight_pct=_q(missing_market_weight),
        undisclosed_equity_weight_pct=_q(undisclosed_equity_weight),
        proxy_weight_pct=_q(configured_proxy_weight),
        fund_holding_weight_pct=_q(fund_weight),
        resolved_fund_holding_weight_pct=_q(resolved_fund_weight),
        unresolved_fund_weight_pct=_q(unresolved_fund_weight),
        cash_weight_pct=_q(cash_weight_pct),
        total_explained_weight_pct=_q(total_explained),
    )
    modeled_risk_weight = priced_weight + priced_proxy_weight + resolved_fund_weight
    predicted: Decimal | None = None
    if modeled_risk_weight > 0:
        predicted = _q(
            (known_contribution or Decimal("0"))
            + (proxy_contribution or Decimal("0"))
            + (fund_contribution or Decimal("0"))
        )
    lower, upper = _prediction_interval(
        predicted,
        prior_residuals=prior_residuals,
        unresolved_security_weight=unresolved_security_weight + missing_market_weight,
        undisclosed_equity_weight=undisclosed_equity_weight,
        priced_proxy_weight=priced_proxy_weight,
        unresolved_fund_weight=unresolved_fund_weight,
    )
    residual = (
        _q(actual_return_pct - predicted)
        if actual_return_pct is not None and predicted is not None
        else None
    )
    return DailyPrediction(
        nav_date=nav_date,
        actual_return_pct=_q(actual_return_pct) if actual_return_pct is not None else None,
        actual_return_source=actual_return_source,
        predicted_return_pct=predicted,
        lower_bound_pct=lower,
        upper_bound_pct=upper,
        known_contribution_pct=_q(known_contribution) if known_contribution is not None else None,
        proxy_contribution_pct=(
            _q(proxy_contribution) if proxy_contribution is not None else None
        ),
        fund_holding_contribution_pct=(
            _q(fund_contribution) if fund_contribution is not None else None
        ),
        cash_contribution_pct=Decimal("0E-8"),
        residual_pct=residual,
        analysis_mode=analysis_mode(report_public_available_at, nav_date),
        confidence=_confidence(
            total_explained,
            len(prior_residuals),
            proxy_confidence=proxy_config.confidence if proxy_config else None,
            proxy_weight=configured_proxy_weight,
        ),
        coverage=coverage,
        security_contributions=security_items,
        proxy_contributions=proxy_items,
        fund_holding_contributions=fund_items,
    )


def analysis_mode(public_available_at: datetime, nav_date: date) -> AnalysisMode:
    return "Q2_EX_POST" if nav_date < public_available_at.date() else "Q2_LIVE"


def load_proxy_config(
    representative_code: str,
    path: Path | None = None,
) -> FundProxyConfig | None:
    document = _load_proxy_document(path)
    funds = document.get("funds")
    if not isinstance(funds, dict):
        raise ValueError("Proxy config must contain a funds object")
    raw = funds.get(representative_code)
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("proxies"), list):
        raise ValueError(f"Proxy config for {representative_code} is invalid")
    if not 1 <= len(raw["proxies"]) <= 2:
        raise ValueError(f"Fund {representative_code} must have one or two proxies")
    proxies: list[ProxyDefinition] = []
    for index, item in enumerate(raw["proxies"]):
        if not isinstance(item, dict):
            raise ValueError(f"Proxy {representative_code}[{index}] must be an object")
        proxies.append(
            ProxyDefinition(
                symbol=_required_text(item, "symbol").upper(),
                currency=_currency(_required_text(item, "currency")),
                weight=Decimal(str(item.get("weight"))),
            )
        )
    if any(item.weight <= 0 for item in proxies):
        raise ValueError(f"Proxy weights for {representative_code} must be positive")
    if abs(_sum(item.weight for item in proxies) - Decimal("1")) > Decimal("0.000001"):
        raise ValueError(f"Proxy weights for {representative_code} must sum to 1")
    confidence = _required_text(raw, "confidence").upper()
    if confidence not in {"HIGH", "MEDIUM", "LOW"}:
        raise ValueError(f"Invalid proxy confidence for {representative_code}")
    return FundProxyConfig(
        representative_code=representative_code,
        proxies=tuple(proxies),
        reason=_required_text(raw, "reason"),
        confidence=confidence,
    )


def load_alignment_override(
    representative_code: str,
    path: Path | None = None,
) -> str | None:
    document = _load_proxy_document(path)
    overrides = document.get("alignment_overrides", {})
    if not isinstance(overrides, dict):
        raise ValueError("alignment_overrides must be an object")
    value = overrides.get(representative_code)
    return _required_text({"value": value}, "value").upper() if value is not None else None


def load_consistency_rule_values(path: Path | None = None) -> dict[str, object]:
    document = _load_proxy_document(path)
    rules = document.get("consistency_rules")
    if not isinstance(rules, dict):
        raise ValueError("Proxy config must contain consistency_rules")
    return dict(rules)


@lru_cache(maxsize=8)
def _load_proxy_document(path: Path | None) -> dict[str, Any]:
    if path is not None:
        return _read_proxy_document(path, require_version=True)

    public = _read_proxy_document(PUBLIC_PROXY_PATH, require_version=True)
    if not LOCAL_PROXY_PATH.is_file():
        return public
    local = _read_proxy_document(LOCAL_PROXY_PATH, require_version=False)
    return _merge_proxy_documents(public, local)


def _read_proxy_document(path: Path, *, require_version: bool) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"Proxy config must be an object: {path}")
    version = document.get("version")
    if (require_version and version != 1) or (version is not None and version != 1):
        raise ValueError(f"Proxy config must have version: 1: {path}")
    return document


def _merge_proxy_documents(
    public: dict[str, Any], local: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(public)
    for field in ("funds", "alignment_overrides", "consistency_rules"):
        base_value = public.get(field, {})
        local_value = local.get(field, {})
        if not isinstance(base_value, dict) or not isinstance(local_value, dict):
            raise ValueError(f"Proxy config field {field} must be an object")
        merged[field] = {**base_value, **local_value}
    return merged


def _security_contribution(item: HoldingReturnInput) -> Contribution:
    return Contribution(
        name=item.name,
        symbol=item.provider_symbol,
        weight_pct=_q(item.weight_pct),
        return_pct=_q(item.return_pct) if item.return_pct is not None else None,
        contribution_pct=(
            _contribution(item.weight_pct, item.return_pct)
            if item.return_pct is not None
            else None
        ),
        trade_date=item.trade_date,
        previous_trade_date=item.previous_trade_date,
        source=item.mapping_source,
        note=item.mapping_reason,
    )


def _fund_holding_contribution(item: FundHoldingReturnInput) -> Contribution:
    return Contribution(
        name=item.name,
        symbol=item.resolved_fund_code,
        weight_pct=_q(item.weight_pct),
        return_pct=_q(item.return_pct) if item.return_pct is not None else None,
        contribution_pct=(
            _contribution(item.weight_pct, item.return_pct)
            if not item.is_unresolved and item.return_pct is not None
            else None
        ),
        trade_date=item.nav_date,
        previous_trade_date=None,
        source="UNDERLYING_FUND_NAV" if not item.is_unresolved else "UNRESOLVED_FUND_HOLDING",
        note=None if not item.is_unresolved else "底层基金未可靠解析，未填入 0 收益",
    )


def _prediction_interval(
    predicted: Decimal | None,
    *,
    prior_residuals: tuple[Decimal, ...],
    unresolved_security_weight: Decimal,
    undisclosed_equity_weight: Decimal,
    priced_proxy_weight: Decimal,
    unresolved_fund_weight: Decimal,
) -> tuple[Decimal | None, Decimal | None]:
    if predicted is None:
        return None, None
    recent = prior_residuals[-10:]
    base_mae = (
        _sum(abs(item) for item in recent) / Decimal(len(recent))
        if len(recent) >= 3
        else Decimal("1.50")
    )
    proxy_gap = max(Decimal("0"), undisclosed_equity_weight - priced_proxy_weight)
    half_width = (
        max(base_mae, Decimal("0.50"))
        + unresolved_security_weight * Decimal("0.03")
        + priced_proxy_weight * Decimal("0.015")
        + proxy_gap * Decimal("0.04")
        + unresolved_fund_weight * Decimal("0.03")
    )
    if len(recent) < 3:
        half_width += Decimal("0.75")
    return _q(predicted - half_width), _q(predicted + half_width)


def _confidence(
    total_explained: Decimal,
    history_count: int,
    *,
    proxy_confidence: str | None,
    proxy_weight: Decimal,
) -> Confidence:
    if proxy_weight > 0 and proxy_confidence == "LOW":
        return "LOW_CONFIDENCE"
    if history_count < 5 or total_explained < Decimal("50"):
        return "LOW_CONFIDENCE"
    if (
        history_count < 10
        or total_explained < Decimal("80")
        or (proxy_weight > 0 and proxy_confidence == "MEDIUM")
    ):
        return "MEDIUM"
    return "HIGH"


def _validate_weight(name: str, value: Decimal) -> None:
    if not value.is_finite() or value < 0 or value > Decimal("100.05"):
        raise ValueError(f"{name} must be a finite percentage between 0 and 100")


def _contribution(weight_pct: Decimal, return_pct: Decimal) -> Decimal:
    return _q(weight_pct * return_pct / Decimal("100"))


def _sum(values: Any) -> Decimal:
    return sum(values, start=Decimal("0"))


def _sum_optional(values: Any) -> Decimal | None:
    present = [value for value in values if value is not None]
    return _sum(present) if present else None


def _q(value: Decimal) -> Decimal:
    return value.quantize(PCT_SCALE, rounding=ROUND_HALF_UP)


def _required_text(document: dict[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _currency(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError(f"Invalid currency: {value!r}")
    return normalized
