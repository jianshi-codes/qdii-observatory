"""End-to-end fund and portfolio analysis over the existing local database."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ingestion.http import ProviderHttpError
from backend.app.ingestion.providers.base import ProviderSchemaError
from backend.app.models import (
    DailyExchangeRate,
    DailyFundNav,
    FundContract,
    FundReport,
    FundShare,
    PortfolioPosition,
    ReportCountryAllocation,
    ReportDerivedMetrics,
    ReportFundHolding,
    ReportIndustryAllocation,
    ReportSecurityHolding,
)
from backend.app.q2_analysis import ANALYSIS_START_DATE, MODEL_NAME
from backend.app.q2_analysis.alignment import align_returns, normalize_policy
from backend.app.q2_analysis.consistency import (
    ConsistencyResult,
    ConsistencyRules,
    CumulativePoint,
    cumulative_points,
    evaluate_consistency,
)
from backend.app.q2_analysis.market_provider import MarketSeries
from backend.app.q2_analysis.predictor import (
    DailyPrediction,
    FundHoldingReturnInput,
    FundProxyConfig,
    HoldingReturnInput,
    ProxyReturnInput,
    load_alignment_override,
    load_consistency_rule_values,
    load_proxy_config,
    predict_day,
)
from backend.app.q2_analysis.scope import AnalysisTarget, validate_analysis_dates
from backend.app.q2_analysis.security_mapping import SecurityMapping, map_security_holding

PCT_SCALE = Decimal("0.00000001")
SEMICONDUCTOR_TOP10_LABEL = "半导体（前十大披露）"

COUNTRY_EXPOSURE_ALIASES = {
    "US": "美国",
    "UNITED_STATES": "美国",
    "美国": "美国",
    "HK": "中国香港",
    "HONG_KONG": "中国香港",
    "香港": "中国香港",
    "中国香港": "中国香港",
    "CN": "中国",
    "CHINA": "中国",
    "中国": "中国",
    "KR": "韩国",
    "SOUTH_KOREA": "韩国",
    "韩国": "韩国",
    "JP": "日本",
    "JAPAN": "日本",
    "日本": "日本",
    "UK": "英国",
    "UNITED_KINGDOM": "英国",
    "英国": "英国",
}

INDUSTRY_EXPOSURE_ALIASES = {
    "INFORMATION_TECHNOLOGY": "信息技术",
    "信息技术": "信息技术",
    "CONSUMER_DISCRETIONARY": "非日常生活消费品",
    "消费者非必需品": "非日常生活消费品",
    "非日常生活消费品": "非日常生活消费品",
    "INDUSTRIALS": "工业",
    "工业": "工业",
    "MATERIALS": "原材料",
    "原材料": "原材料",
    "COMMUNICATION_SERVICES": "通信服务",
    "电信服务": "通信服务",
    "通信服务": "通信服务",
    "FINANCIALS": "金融",
    "金融": "金融",
    "HEALTHCARE": "医疗保健",
    "HEALTH_CARE": "医疗保健",
    "保健": "医疗保健",
    "保健HEALTHCARE": "医疗保健",
    "医疗保健": "医疗保健",
    "ENERGY": "能源",
    "能源": "能源",
    "CONSUMER_STAPLES": "日常生活消费品",
    "日常消费品": "日常生活消费品",
    "日常生活消费品": "日常生活消费品",
    "非周期性消费品": "日常生活消费品",
    "UTILITIES": "公用事业",
    "公用事业": "公用事业",
    "REAL_ESTATE": "房地产",
    "房地产": "房地产",
    "UNCLASSIFIED": "未分类",
    "未分类": "未分类",
}


class MarketSeriesProvider(Protocol):
    name: str
    version: str

    def fetch_series(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        *,
        refresh: bool = False,
        no_cache: bool = False,
    ) -> MarketSeries: ...

    def fetch_fx_series(
        self,
        base_currency: str,
        quote_currency: str,
        start_date: date,
        end_date: date,
        *,
        refresh: bool = False,
        no_cache: bool = False,
    ) -> MarketSeries | None: ...


@dataclass(frozen=True, slots=True)
class AnalysisSource:
    source_type: str
    provider: str
    url: str | None
    data_date: date | None
    fetched_at: datetime | None


@dataclass(frozen=True, slots=True)
class FundAnalysisResult:
    target: AnalysisTarget
    data_as_of: date
    market_data_fetched_at: datetime | None
    report_period_end: date
    report_public_available_at: datetime
    analysis_start_date: date
    as_of: date
    predictions: tuple[DailyPrediction, ...]
    consistency: ConsistencyResult
    proxy_config: FundProxyConfig | None
    prediction_observation_coverage_pct: Decimal | None
    unmapped_securities: tuple[dict[str, Any], ...]
    limitations: tuple[str, ...]
    sources: tuple[AnalysisSource, ...]
    market_data_errors: tuple[str, ...]

    @property
    def latest_prediction(self) -> DailyPrediction | None:
        return self.predictions[-1] if self.predictions else None

    @property
    def latest_comparison(self) -> DailyPrediction | None:
        return next(
            (
                item
                for item in reversed(self.predictions)
                if item.actual_return_pct is not None
                and item.predicted_return_pct is not None
            ),
            None,
        )

    def as_dict(self, *, include_series: bool = True) -> dict[str, Any]:
        latest = self.latest_prediction
        prediction_payload = latest.as_dict() if latest else None
        if latest is not None and prediction_payload is not None:
            prediction_payload["estimate_date"] = _next_weekday(latest.nav_date)
        comparison = self.latest_comparison
        comparison_payload = None
        if comparison is not None:
            assert comparison.actual_return_pct is not None
            assert comparison.predicted_return_pct is not None
            comparison_payload = {
                "comparison_date": _next_weekday(comparison.nav_date),
                "nav_date": comparison.nav_date,
                "predicted_return_pct": comparison.predicted_return_pct,
                "actual_return_pct": comparison.actual_return_pct,
                "actual_return_source": comparison.actual_return_source,
                "analysis_mode": comparison.analysis_mode,
                "actual_minus_predicted_pct": _q(
                    comparison.actual_return_pct - comparison.predicted_return_pct
                ),
            }
        result: dict[str, Any] = {
            "fund_id": self.target.fund_id,
            "fund_code": self.target.share_code,
            "representative_code": self.target.representative_code,
            "fund_name": self.target.fund_name,
            "share_code": self.target.share_code,
            "share_currency": self.target.share_currency,
            "data_as_of": self.data_as_of,
            "market_data_fetched_at": self.market_data_fetched_at,
            "report_period_end": self.report_period_end,
            "report_public_available_at": self.report_public_available_at,
            "analysis_start_date": self.analysis_start_date,
            "as_of": self.as_of,
            "analysis_mode": latest.analysis_mode if latest else None,
            "model": MODEL_NAME,
            "prediction": prediction_payload,
            "latest_comparison": comparison_payload,
            "consistency": self.consistency.as_dict(),
            "coverage": asdict(latest.coverage) if latest else None,
            "prediction_observation_coverage_pct": (
                self.prediction_observation_coverage_pct
            ),
            "proxies": _proxy_payload(self.proxy_config),
            "unmapped_securities": list(self.unmapped_securities),
            "limitations": list(self.limitations),
            "sources": [asdict(item) for item in self.sources],
            "market_data_errors": list(self.market_data_errors),
        }
        if include_series:
            result["series"] = [asdict(item) for item in cumulative_points(list(self.predictions))]
        return result


@dataclass(frozen=True, slots=True)
class PortfolioAnalysisResult:
    data_as_of: date
    market_data_fetched_at: datetime | None
    analysis_start_date: date
    as_of: date
    fund_results: tuple[FundAnalysisResult, ...]
    funds: tuple[dict[str, Any], ...]
    portfolio_prediction_pct: Decimal | None
    portfolio_lower_bound_pct: Decimal | None
    portfolio_upper_bound_pct: Decimal | None
    analyzed_portfolio_weight_pct: Decimal | None
    country_exposure: tuple[dict[str, Any], ...]
    industry_exposure: tuple[dict[str, Any], ...]
    overlaps: tuple[dict[str, Any], ...]
    limitations: tuple[str, ...]
    sources: tuple[AnalysisSource, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "data_as_of": self.data_as_of,
            "market_data_fetched_at": self.market_data_fetched_at,
            "analysis_start_date": self.analysis_start_date,
            "as_of": self.as_of,
            "portfolio_prediction": {
                "predicted_return_pct": self.portfolio_prediction_pct,
                "lower_bound_pct": self.portfolio_lower_bound_pct,
                "upper_bound_pct": self.portfolio_upper_bound_pct,
                "analyzed_portfolio_weight_pct": self.analyzed_portfolio_weight_pct,
            },
            "funds": list(self.funds),
            "country_exposure": list(self.country_exposure),
            "industry_exposure": list(self.industry_exposure),
            "overlaps": list(self.overlaps),
            "limitations": list(self.limitations),
            "sources": [asdict(item) for item in self.sources],
        }


class _MarketLoader:
    def __init__(
        self,
        provider: MarketSeriesProvider,
        *,
        start_date: date,
        as_of: date,
        refresh: bool,
        no_cache: bool,
    ) -> None:
        self.provider = provider
        self.start_date = start_date
        self.as_of = as_of
        self.refresh = refresh
        self.no_cache = no_cache
        self.series: dict[str, MarketSeries | None] = {}
        self.errors: dict[str, str] = {}

    @staticmethod
    def security_key(symbol: str, expected_currency: str) -> str:
        return f"SECURITY:{symbol}:{expected_currency.upper()}"

    @staticmethod
    def fx_key(base_currency: str, quote_currency: str) -> str:
        return f"FX:{base_currency.upper()}{quote_currency.upper()}"

    def security(self, symbol: str, expected_currency: str) -> MarketSeries | None:
        key = self.security_key(symbol, expected_currency)
        if key not in self.series:
            try:
                value = self.provider.fetch_series(
                    symbol,
                    self.start_date,
                    self.as_of,
                    refresh=self.refresh,
                    no_cache=self.no_cache,
                )
                if not _currency_matches(expected_currency, value.currency):
                    raise ProviderSchemaError(
                        f"{symbol} currency mismatch: expected {expected_currency}, "
                        f"provider returned {value.currency}"
                    )
                self.series[key] = value
            except (ProviderHttpError, ProviderSchemaError) as error:
                self.series[key] = None
                self.errors[key] = str(error)
        return self.series[key]

    def fx(self, base_currency: str, quote_currency: str) -> MarketSeries | None:
        base = base_currency.upper()
        quote = quote_currency.upper()
        if base == quote:
            return None
        key = self.fx_key(base, quote)
        if key not in self.series:
            try:
                value = self.provider.fetch_fx_series(
                    base,
                    quote,
                    self.start_date,
                    self.as_of,
                    refresh=self.refresh,
                    no_cache=self.no_cache,
                )
                if value is None or not _currency_matches(quote, value.currency):
                    returned = value.currency if value is not None else "NONE"
                    raise ProviderSchemaError(
                        f"{base}/{quote} currency mismatch: provider returned {returned}"
                    )
                self.series[key] = value
            except (ProviderHttpError, ProviderSchemaError) as error:
                self.series[key] = None
                self.errors[key] = str(error)
        return self.series[key]

    def fetched_series(self, keys: set[str] | None = None) -> list[MarketSeries]:
        selected = self.series.items() if keys is None else (
            (key, self.series[key]) for key in keys if key in self.series
        )
        return [item for _, item in selected if item is not None]

    def errors_for(self, keys: set[str]) -> dict[str, str]:
        return {key: self.errors[key] for key in keys if key in self.errors}


def analyze_fund(
    session: Session,
    target: AnalysisTarget,
    provider: MarketSeriesProvider,
    *,
    start_date: date = ANALYSIS_START_DATE,
    as_of: date,
    refresh_market_data: bool = False,
    no_cache: bool = False,
    _market_loader: _MarketLoader | None = None,
) -> FundAnalysisResult:
    validate_analysis_dates(start_date, as_of)
    report = session.get(FundReport, target.report_id)
    if report is None or report.public_available_at is None:
        raise ValueError(f"Q2 report {target.report_id} is unavailable or lacks public date")
    holdings = tuple(
        session.scalars(
            select(ReportSecurityHolding)
            .where(
                ReportSecurityHolding.fund_report_id == report.id,
                ReportSecurityHolding.exposure_basis == "DIRECT",
                ReportSecurityHolding.security_type == "EQUITY",
                ReportSecurityHolding.nav_pct.is_not(None),
                ReportSecurityHolding.nav_pct > 0,
            )
            .order_by(
                ReportSecurityHolding.rank.asc().nulls_last(),
                ReportSecurityHolding.id,
            )
        ).all()
    )
    fund_holdings = tuple(
        session.scalars(
            select(ReportFundHolding)
            .where(
                ReportFundHolding.fund_report_id == report.id,
                ReportFundHolding.exposure_basis == "DIRECT",
                ReportFundHolding.nav_pct.is_not(None),
                ReportFundHolding.nav_pct > 0,
            )
            .order_by(ReportFundHolding.rank.asc().nulls_last(), ReportFundHolding.id)
        ).all()
    )
    metrics = session.scalar(
        select(ReportDerivedMetrics).where(ReportDerivedMetrics.fund_report_id == report.id)
    )
    if (
        metrics is None
        or metrics.equity_nav_pct is None
        or metrics.cash_and_other_pct is None
    ):
        raise ValueError(
            f"Q2 report {report.id} lacks required derived allocation metrics; "
            "refusing to infer undisclosed allocation as cash"
        )
    equity_weight = metrics.equity_nav_pct
    cash_weight = metrics.cash_and_other_pct
    latest_comparable_nav_date = _latest_comparable_nav_date(as_of)
    nav_rows = tuple(
        session.scalars(
            select(DailyFundNav)
            .where(
                DailyFundNav.fund_share_id == target.share_id,
                DailyFundNav.nav_date >= start_date,
                DailyFundNav.nav_date <= latest_comparable_nav_date,
            )
            .order_by(DailyFundNav.nav_date, DailyFundNav.id)
        ).all()
    )
    analysis_dates = [item.nav_date for item in nav_rows]
    appended_estimate = (
        latest_comparable_nav_date >= start_date
        and (
            not analysis_dates
            or analysis_dates[-1] < latest_comparable_nav_date
        )
    )
    if appended_estimate:
        analysis_dates.append(latest_comparable_nav_date)
    actual_by_date = {item.nav_date: _actual_return(item) for item in nav_rows}

    loader = _market_loader or _MarketLoader(
        provider,
        start_date=start_date,
        as_of=as_of,
        refresh=refresh_market_data,
        no_cache=no_cache,
    )
    used_market_keys: set[str] = set()
    mappings = {item.id: map_security_holding(item) for item in holdings}
    alignment_override = load_alignment_override(target.representative_code)
    policy = (
        normalize_policy(alignment_override)
        if alignment_override
        else "QDII_SAME_VALUATION_SESSION"
    )
    security_returns: dict[int, dict[date, Any]] = {}
    for holding in holdings:
        mapping = mappings[holding.id]
        if not mapping.is_mapped:
            security_returns[holding.id] = {}
            continue
        assert mapping.provider_symbol is not None
        assert mapping.currency is not None
        used_market_keys.add(
            loader.security_key(mapping.provider_symbol, mapping.currency)
        )
        price_series = loader.security(mapping.provider_symbol, mapping.currency)
        if price_series is None:
            security_returns[holding.id] = {}
            continue
        if mapping.currency.upper() != target.share_currency.upper():
            used_market_keys.add(loader.fx_key(mapping.currency, target.share_currency))
        fx_series = loader.fx(mapping.currency, target.share_currency)
        aligned = align_returns(
            analysis_dates,
            price_series,
            security_market=mapping.market,
            security_currency=mapping.currency,
            share_currency=target.share_currency,
            fx_series=fx_series,
            policy=policy,
        )
        security_returns[holding.id] = {item.nav_date: item for item in aligned}

    proxy_config = load_proxy_config(target.representative_code)
    proxy_returns: dict[str, dict[date, Any]] = {}
    if proxy_config is not None:
        for proxy in proxy_config.proxies:
            used_market_keys.add(loader.security_key(proxy.symbol, proxy.currency))
            price_series = loader.security(proxy.symbol, proxy.currency)
            if price_series is None:
                proxy_returns[proxy.symbol] = {}
                continue
            if proxy.currency.upper() != target.share_currency.upper():
                used_market_keys.add(loader.fx_key(proxy.currency, target.share_currency))
            fx_series = loader.fx(proxy.currency, target.share_currency)
            aligned = align_returns(
                analysis_dates,
                price_series,
                security_market=_proxy_market(proxy.symbol),
                security_currency=proxy.currency,
                share_currency=target.share_currency,
                fx_series=fx_series,
                policy=policy,
            )
            proxy_returns[proxy.symbol] = {item.nav_date: item for item in aligned}

    underlying_returns = _underlying_fund_returns(
        session, fund_holdings, start_date=start_date, as_of=as_of
    )
    predictions: list[DailyPrediction] = []
    residuals: list[Decimal] = []
    for nav_date in analysis_dates:
        actual_return, actual_source = actual_by_date.get(nav_date, (None, None))
        holding_inputs = tuple(
            _holding_input(
                holding,
                mappings[holding.id],
                security_returns[holding.id].get(nav_date),
            )
            for holding in holdings
        )
        proxy_inputs = _proxy_inputs(proxy_config, proxy_returns, nav_date)
        fund_inputs = tuple(
            _fund_holding_input(
                holding,
                underlying_returns.get(holding.id, {}).get(nav_date),
            )
            for holding in fund_holdings
        )
        prediction = predict_day(
            nav_date=nav_date,
            actual_return_pct=actual_return,
            actual_return_source=actual_source,
            report_public_available_at=report.public_available_at,
            holdings=holding_inputs,
            equity_nav_pct=equity_weight,
            fund_holdings=fund_inputs,
            cash_weight_pct=cash_weight,
            proxy_config=proxy_config,
            proxy_returns=proxy_inputs,
            prior_residuals=tuple(residuals),
        )
        predictions.append(prediction)
        if prediction.residual_pct is not None:
            residuals.append(prediction.residual_pct)

    rules = ConsistencyRules.from_mapping(load_consistency_rule_values())
    consistency_predictions = predictions[:-1] if appended_estimate else predictions
    consistency = evaluate_consistency(consistency_predictions, rules)
    fetched_series = loader.fetched_series(used_market_keys)
    market_errors = loader.errors_for(used_market_keys)
    data_dates = [item.nav_date for item in nav_rows]
    data_dates.extend(point.trade_date for series in fetched_series for point in series.points)
    data_as_of = max(data_dates) if data_dates else as_of
    market_fetched_at = max(
        (item.fetched_at for item in fetched_series),
        default=None,
    )
    unmapped = tuple(
        {
            "security_name": item.security_name_normalized,
            "security_code_raw": item.security_code_raw,
            "market": mappings[item.id].market,
            "weight_pct": item.nav_pct,
            "reason": mappings[item.id].reason,
        }
        for item in holdings
        if not mappings[item.id].is_mapped
    )
    limitations = _fund_limitations(
        predictions,
        proxy_config=proxy_config,
        unmapped=unmapped,
        market_errors=market_errors,
        has_unresolved_funds=any(
            item.is_unresolved or item.resolved_fund_contract_id is None
            for item in fund_holdings
        ),
    )
    sources = _fund_sources(report, nav_rows, fetched_series)
    return FundAnalysisResult(
        target=target,
        data_as_of=data_as_of,
        market_data_fetched_at=market_fetched_at,
        report_period_end=report.period_end,
        report_public_available_at=report.public_available_at,
        analysis_start_date=start_date,
        as_of=as_of,
        predictions=tuple(predictions),
        consistency=consistency,
        proxy_config=proxy_config,
        prediction_observation_coverage_pct=_observation_coverage(predictions),
        unmapped_securities=unmapped,
        limitations=limitations,
        sources=sources,
        market_data_errors=tuple(f"{key}: {value}" for key, value in market_errors.items()),
    )


def analyze_portfolio(
    session: Session,
    targets: list[AnalysisTarget],
    provider: MarketSeriesProvider,
    *,
    start_date: date = ANALYSIS_START_DATE,
    as_of: date,
    refresh_market_data: bool = False,
    no_cache: bool = False,
) -> PortfolioAnalysisResult:
    validate_analysis_dates(start_date, as_of)
    loader = _MarketLoader(
        provider,
        start_date=start_date,
        as_of=as_of,
        refresh=refresh_market_data,
        no_cache=no_cache,
    )
    results = tuple(
        analyze_fund(
            session,
            target,
            provider,
            start_date=start_date,
            as_of=as_of,
            refresh_market_data=refresh_market_data,
            no_cache=no_cache,
            _market_loader=loader,
        )
        for target in targets
    )
    position_values, total_value, value_limitations = _position_values_cny(
        session,
        targets,
        start_date=start_date,
        as_of=as_of,
    )
    result_weights = {
        result.target.share_id: (
            position_values.get(result.target.share_id, Decimal("0")) / total_value
            if total_value is not None and total_value > 0
            else Decimal("0")
        )
        for result in results
    }
    prediction, lower, upper, analyzed_weight = _portfolio_prediction(
        results,
        result_weights,
        portfolio_valuation_complete=total_value is not None and total_value > 0,
    )
    contract_weights: dict[int, Decimal] = defaultdict(Decimal)
    for result in results:
        contract_weights[result.target.fund_id] += result_weights[result.target.share_id]
    funds = _portfolio_fund_rows(results, result_weights)
    country = _weighted_allocations(
        session,
        results,
        contract_weights,
        allocation_type="country",
    )
    industry = _weighted_allocations(
        session,
        results,
        contract_weights,
        allocation_type="industry",
    )
    overlaps = _portfolio_overlaps(session, results)
    sources = _unique_sources(item for result in results for item in result.sources)
    limitations = tuple(
        dict.fromkeys(
            [
                "组合预计收益按当前本地持仓参考市值加权，不代表交易账户实时资产。",
                "组合重叠仅基于 2026 Q2 直接披露证券，不反推当前真实持仓。",
                *(
                    [
                        f"{SEMICONDUCTOR_TOP10_LABEL}是各基金报告衍生指标的组合加权值，"
                        "与行业暴露重叠，不可相加。"
                    ]
                    if any(item["name"] == SEMICONDUCTOR_TOP10_LABEL for item in industry)
                    else []
                ),
                *value_limitations,
                *(item for result in results for item in result.limitations),
            ]
        )
    )
    return PortfolioAnalysisResult(
        data_as_of=max((item.data_as_of for item in results), default=as_of),
        market_data_fetched_at=max(
            (
                item.market_data_fetched_at
                for item in results
                if item.market_data_fetched_at is not None
            ),
            default=None,
        ),
        analysis_start_date=start_date,
        as_of=as_of,
        fund_results=results,
        funds=funds,
        portfolio_prediction_pct=prediction,
        portfolio_lower_bound_pct=lower,
        portfolio_upper_bound_pct=upper,
        analyzed_portfolio_weight_pct=analyzed_weight,
        country_exposure=country,
        industry_exposure=industry,
        overlaps=overlaps,
        limitations=limitations,
        sources=sources,
    )


def _actual_return(row: DailyFundNav) -> tuple[Decimal | None, str | None]:
    if row.published_daily_return_pct is not None:
        return row.published_daily_return_pct, "PUBLISHED_DAILY_RETURN"
    if row.calculated_daily_return_pct is not None:
        return row.calculated_daily_return_pct, "CALCULATED_FROM_ARCHIVED_NAV"
    return None, None


def _holding_input(
    holding: ReportSecurityHolding,
    mapping: SecurityMapping,
    aligned: Any | None,
) -> HoldingReturnInput:
    assert holding.nav_pct is not None
    return HoldingReturnInput(
        name=holding.security_name_normalized,
        raw_code=holding.security_code_raw,
        provider_symbol=mapping.provider_symbol,
        market=mapping.market,
        currency=mapping.currency,
        mapping_source=mapping.source,
        mapping_reason=mapping.reason,
        weight_pct=holding.nav_pct,
        trade_date=aligned.trade_date if aligned else None,
        previous_trade_date=aligned.previous_trade_date if aligned else None,
        return_pct=aligned.share_currency_return_pct if aligned else None,
        alignment_policy=aligned.alignment_policy if aligned else None,
    )


def _proxy_inputs(
    config: FundProxyConfig | None,
    aligned_by_symbol: dict[str, dict[date, Any]],
    nav_date: date,
) -> tuple[ProxyReturnInput, ...]:
    if config is None:
        return ()
    result = []
    for proxy in config.proxies:
        aligned = aligned_by_symbol.get(proxy.symbol, {}).get(nav_date)
        result.append(
            ProxyReturnInput(
                symbol=proxy.symbol,
                currency=proxy.currency,
                basket_weight=proxy.weight,
                trade_date=aligned.trade_date if aligned else None,
                previous_trade_date=aligned.previous_trade_date if aligned else None,
                return_pct=aligned.share_currency_return_pct if aligned else None,
                alignment_policy=(
                    aligned.alignment_policy
                    if aligned
                    else "US_PREVIOUS_COMPLETED_SESSION"
                ),
            )
        )
    return tuple(result)


def _proxy_market(symbol: str) -> str:
    normalized = symbol.upper()
    if normalized == "^HSI" or normalized.endswith(".HK"):
        return "HK"
    if normalized.endswith(".T"):
        return "JP"
    if normalized.endswith(".KS"):
        return "KR"
    if normalized.endswith(".SS"):
        return "CN_SH"
    if normalized.endswith(".SZ"):
        return "CN_SZ"
    if normalized.endswith(".L"):
        return "UK"
    return "US"


def _underlying_fund_returns(
    session: Session,
    holdings: tuple[ReportFundHolding, ...],
    *,
    start_date: date,
    as_of: date,
) -> dict[int, dict[date, tuple[date, Decimal]]]:
    result: dict[int, dict[date, tuple[date, Decimal]]] = {}
    for holding in holdings:
        if holding.is_unresolved or holding.resolved_fund_contract_id is None:
            result[holding.id] = {}
            continue
        contract = session.get(FundContract, holding.resolved_fund_contract_id)
        if contract is None:
            result[holding.id] = {}
            continue
        share = session.scalar(
            select(FundShare)
            .where(FundShare.fund_contract_id == contract.id)
            .order_by(
                (FundShare.share_code == contract.representative_code).desc(),
                FundShare.share_code,
            )
            .limit(1)
        )
        if share is None:
            result[holding.id] = {}
            continue
        rows = session.scalars(
            select(DailyFundNav)
            .where(
                DailyFundNav.fund_share_id == share.id,
                DailyFundNav.nav_date >= start_date,
                DailyFundNav.nav_date <= as_of,
            )
            .order_by(DailyFundNav.nav_date)
        ).all()
        result[holding.id] = {
            row.nav_date: (row.nav_date, value)
            for row in rows
            for value, _ in [_actual_return(row)]
            if value is not None
        }
    return result


def _fund_holding_input(
    holding: ReportFundHolding,
    value: tuple[date, Decimal] | None,
) -> FundHoldingReturnInput:
    assert holding.nav_pct is not None
    code = (
        holding.resolved_fund_contract.representative_code
        if holding.resolved_fund_contract is not None
        else None
    )
    return FundHoldingReturnInput(
        name=holding.fund_name_normalized,
        raw_code=holding.fund_code_raw,
        resolved_fund_code=code,
        weight_pct=holding.nav_pct,
        nav_date=value[0] if value else None,
        return_pct=value[1] if value else None,
        is_unresolved=holding.is_unresolved or code is None,
    )


def _fund_limitations(
    predictions: list[DailyPrediction],
    *,
    proxy_config: FundProxyConfig | None,
    unmapped: tuple[dict[str, Any], ...],
    market_errors: dict[str, str],
    has_unresolved_funds: bool,
) -> tuple[str, ...]:
    limitations = [
        "模型只使用 2026 Q2 期末静态披露持仓，不代表基金当前真实持仓。",
        "Q2_EX_POST 仅为事后解释力检查，不是当时可获得的预测。",
        "现金及其他仓位首版收益贡献按 0 处理，并在覆盖率中单独显示。",
        "行情采用公开日线调整收盘价；不包含盘中估值，也不生成自动交易指令。",
        "残差不能识别具体证券买卖，可能同时来自调仓、未披露持仓、现金、"
        "基金投资、汇率时点、衍生品或其他组合因素。",
    ]
    if proxy_config is None:
        limitations.append("未披露股票仓位没有可靠代理，保持 unresolved。")
    if unmapped:
        limitations.append(f"有 {len(unmapped)} 只披露证券尚未可靠映射行情代码。")
    if market_errors:
        limitations.append(f"有 {len(market_errors)} 个行情或汇率序列获取/校验失败。")
    if has_unresolved_funds:
        limitations.append("披露的部分基金投资未可靠解析，未把其收益填为 0。")
    if predictions and predictions[-1].actual_return_pct is None:
        limitations.append("最新一条为按 as_of 生成的估算点，尚无同日实际基金净值收益。")
    return tuple(limitations)


def _fund_sources(
    report: FundReport,
    nav_rows: tuple[DailyFundNav, ...],
    market_series: list[MarketSeries],
) -> tuple[AnalysisSource, ...]:
    sources = [
        AnalysisSource(
            source_type="Q2_REPORT",
            provider=report.source_provider,
            url=report.document_url or report.source_page_url,
            data_date=report.period_end,
            fetched_at=report.created_at,
        )
    ]
    latest_nav_by_provider: dict[str, DailyFundNav] = {}
    for row in nav_rows:
        current = latest_nav_by_provider.get(row.source_provider)
        if current is None or row.nav_date > current.nav_date:
            latest_nav_by_provider[row.source_provider] = row
    sources.extend(
        AnalysisSource(
            source_type="FUND_NAV",
            provider=provider,
            url=None,
            data_date=row.nav_date,
            fetched_at=row.fetched_at,
        )
        for provider, row in latest_nav_by_provider.items()
    )
    sources.extend(
        AnalysisSource(
            source_type="MARKET_OR_FX_PRICE",
            provider=item.source_provider,
            url=item.source_url,
            data_date=item.points[-1].trade_date,
            fetched_at=item.fetched_at,
        )
        for item in market_series
    )
    return _unique_sources(sources)


def _observation_coverage(predictions: list[DailyPrediction]) -> Decimal | None:
    actual = [item for item in predictions if item.actual_return_pct is not None]
    if not actual:
        return None
    paired = sum(item.predicted_return_pct is not None for item in actual)
    return _q(Decimal(paired) / Decimal(len(actual)) * Decimal("100"))


def _position_values_cny(
    session: Session,
    targets: list[AnalysisTarget],
    *,
    start_date: date,
    as_of: date,
) -> tuple[dict[int, Decimal], Decimal | None, list[str]]:
    share_ids = {item.share_id for item in targets}
    positions = session.scalars(
        select(PortfolioPosition).where(
            PortfolioPosition.is_active.is_(True),
            PortfolioPosition.snapshot_date <= as_of,
        )
    ).all()
    usd_cny = session.scalar(
        select(DailyExchangeRate)
        .where(
            DailyExchangeRate.base_currency == "USD",
            DailyExchangeRate.quote_currency == "CNY",
            DailyExchangeRate.rate_date >= start_date,
            DailyExchangeRate.rate_date <= as_of,
        )
        .order_by(DailyExchangeRate.rate_date.desc(), DailyExchangeRate.id.desc())
        .limit(1)
    )
    values: dict[int, Decimal] = defaultdict(Decimal)
    limitations: list[str] = []
    total_value = Decimal("0")
    complete = True
    for position in positions:
        latest_nav = session.scalar(
            select(DailyFundNav)
            .where(
                DailyFundNav.fund_share_id == position.fund_share_id,
                DailyFundNav.nav_date >= start_date,
                DailyFundNav.nav_date <= as_of,
            )
            .order_by(DailyFundNav.nav_date.desc(), DailyFundNav.id.desc())
            .limit(1)
        )
        if latest_nav is not None:
            unit_nav = latest_nav.unit_nav
        elif position.anchor_nav_date >= start_date:
            unit_nav = position.anchor_unit_nav
        else:
            complete = False
            limitations.append(
                f"份额 {position.fund_share.share_code} 缺少分析边界内的可靠净值；"
                "组合权重与组合预计收益未计算。"
            )
            continue
        units = position.reported_units
        market_value = units * unit_nav
        if position.currency == "CNY":
            market_value_cny = market_value
        elif position.currency == "USD" and usd_cny is not None:
            market_value_cny = market_value * usd_cny.rate
        else:
            complete = False
            limitations.append(
                f"份额 {position.fund_share.share_code} 缺少分析边界内的可靠人民币折算汇率；"
                "组合权重与组合预计收益未计算。"
            )
            continue
        total_value += market_value_cny
        if position.fund_share_id in share_ids:
            values[position.fund_share_id] += market_value_cny
    if not positions:
        limitations.append("as_of 当日或之前没有可用于组合加权的当前持仓快照。")
        complete = False
    if complete and total_value <= 0:
        limitations.append("当前持仓参考市值合计不大于零，无法计算组合权重。")
        complete = False
    return dict(values), total_value if complete else None, limitations


def _portfolio_prediction(
    results: tuple[FundAnalysisResult, ...],
    weights: dict[int, Decimal],
    *,
    portfolio_valuation_complete: bool,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    available_weight = Decimal("0")
    predicted = lower = upper = Decimal("0")
    complete = True
    for result in results:
        weight = weights.get(result.target.share_id, Decimal("0"))
        latest = result.latest_prediction
        if weight == 0:
            continue
        if (
            latest is None
            or latest.predicted_return_pct is None
            or latest.lower_bound_pct is None
            or latest.upper_bound_pct is None
        ):
            complete = False
            continue
        available_weight += weight
        predicted += weight * latest.predicted_return_pct
        lower += weight * latest.lower_bound_pct
        upper += weight * latest.upper_bound_pct
    analyzed = (
        _q(available_weight * Decimal("100"))
        if portfolio_valuation_complete
        else None
    )
    if (
        not portfolio_valuation_complete
        or not complete
        or abs(available_weight - Decimal("1")) > PCT_SCALE
    ):
        return None, None, None, analyzed
    return _q(predicted), _q(lower), _q(upper), analyzed


def _portfolio_fund_rows(
    results: tuple[FundAnalysisResult, ...], weights: dict[int, Decimal]
) -> tuple[dict[str, Any], ...]:
    grouped: dict[int, list[FundAnalysisResult]] = defaultdict(list)
    for result in results:
        grouped[result.target.fund_id].append(result)
    rows = []
    for fund_results in grouped.values():
        group_weight = sum(
            (weights.get(item.target.share_id, Decimal("0")) for item in fund_results),
            start=Decimal("0"),
        )
        positive_results = [
            (item, weights.get(item.target.share_id, Decimal("0")))
            for item in fund_results
            if weights.get(item.target.share_id, Decimal("0")) > 0
        ]
        latest_predictions = [item.latest_prediction for item, _ in positive_results]
        latest_dates = {
            item.nav_date for item in latest_predictions if item is not None
        }
        prediction_nav_date = (
            next(iter(latest_dates))
            if group_weight > 0
            and len(latest_predictions) == len(positive_results)
            and all(item is not None for item in latest_predictions)
            and len(latest_dates) == 1
            else None
        )
        weighted_prediction = None
        if (
            prediction_nav_date is not None
            and all(
                item is not None and item.predicted_return_pct is not None
                for item in latest_predictions
            )
        ):
            weighted_prediction = _q(
                sum(
                    (
                        weight * item.predicted_return_pct
                        for (_, weight), item in zip(
                            positive_results, latest_predictions, strict=True
                        )
                        if item is not None and item.predicted_return_pct is not None
                    ),
                    start=Decimal("0"),
                )
                / group_weight
            )

        comparable_by_result = [
            {
                item.nav_date: item
                for item in result.predictions
                if item.actual_return_pct is not None
                and item.predicted_return_pct is not None
            }
            for result, _ in positive_results
        ]
        common_comparison_dates = (
            set.intersection(*(set(items) for items in comparable_by_result))
            if comparable_by_result
            else set()
        )
        comparison_nav_date = (
            max(common_comparison_dates)
            if group_weight > 0 and common_comparison_dates
            else None
        )
        comparison_analysis_mode = None
        comparison_predicted = actual_return = actual_minus_predicted = None
        if comparison_nav_date is not None:
            comparison_modes = {
                comparable_by_result[index][comparison_nav_date].analysis_mode
                for index in range(len(positive_results))
            }
            if len(comparison_modes) != 1:
                comparison_nav_date = None
            else:
                comparison_analysis_mode = next(iter(comparison_modes))
        if comparison_nav_date is not None:
            comparison_predicted = _q(
                sum(
                    (
                        weight
                        * cast(
                            Decimal,
                            comparable_by_result[index][
                                comparison_nav_date
                            ].predicted_return_pct,
                        )
                        for index, (_, weight) in enumerate(positive_results)
                    ),
                    start=Decimal("0"),
                )
                / group_weight
            )
            actual_return = _q(
                sum(
                    (
                        weight
                        * cast(
                            Decimal,
                            comparable_by_result[index][
                                comparison_nav_date
                            ].actual_return_pct,
                        )
                        for index, (_, weight) in enumerate(positive_results)
                    ),
                    start=Decimal("0"),
                )
                / group_weight
            )
            actual_minus_predicted = _q(actual_return - comparison_predicted)
        quarter_cumulative_actual = None
        quarter_cumulative_predicted = None
        quarter_cumulative_difference = None
        quarter_observation_count = None
        common_cumulative = (
            _common_cumulative_points(
                tuple(result.predictions for result, _ in positive_results),
                comparison_nav_date,
            )
            if comparison_nav_date is not None
            else None
        )
        if common_cumulative is not None:
            cumulative_by_result, common_observation_count = common_cumulative
            if len(cumulative_by_result) == len(positive_results):
                quarter_cumulative_actual = _q(
                    sum(
                        (
                            weight
                            * cast(
                                Decimal,
                                cumulative_by_result[index].cumulative_actual_return_pct,
                            )
                            for index, (_, weight) in enumerate(positive_results)
                        ),
                        start=Decimal("0"),
                    )
                    / group_weight
                )
                quarter_cumulative_predicted = _q(
                    sum(
                        (
                            weight
                            * cast(
                                Decimal,
                                cumulative_by_result[
                                    index
                                ].cumulative_predicted_return_pct,
                            )
                            for index, (_, weight) in enumerate(positive_results)
                        ),
                        start=Decimal("0"),
                    )
                    / group_weight
                )
                quarter_cumulative_difference = _q(
                    quarter_cumulative_actual - quarter_cumulative_predicted
                )
                quarter_observation_count = common_observation_count
        primary = fund_results[0]
        coverage_pct = min(
            (
                item.latest_prediction.coverage.total_explained_weight_pct
                for item in fund_results
                if item.latest_prediction is not None
            ),
            default=None,
        )
        rows.append(
            {
                "fund_id": primary.target.fund_id,
                "representative_code": primary.target.representative_code,
                "fund_name": primary.target.fund_name,
                "share_codes": [item.target.share_code for item in fund_results],
                "report_period_end": primary.report_period_end,
                "report_public_available_at": primary.report_public_available_at,
                "portfolio_weight_pct": _q(group_weight * Decimal("100")),
                "prediction_date": (
                    _next_weekday(prediction_nav_date)
                    if prediction_nav_date is not None
                    else None
                ),
                "prediction_nav_date": prediction_nav_date,
                "predicted_return_pct": weighted_prediction,
                "comparison_date": (
                    _next_weekday(comparison_nav_date)
                    if comparison_nav_date is not None
                    else None
                ),
                "comparison_nav_date": comparison_nav_date,
                "comparison_analysis_mode": comparison_analysis_mode,
                "comparison_predicted_return_pct": comparison_predicted,
                "actual_return_pct": actual_return,
                "actual_minus_predicted_pct": actual_minus_predicted,
                "quarter_cumulative_through_date": (
                    _next_weekday(comparison_nav_date)
                    if quarter_cumulative_actual is not None
                    and comparison_nav_date is not None
                    else None
                ),
                "quarter_cumulative_through_nav_date": (
                    comparison_nav_date
                    if quarter_cumulative_actual is not None
                    else None
                ),
                "quarter_cumulative_actual_return_pct": quarter_cumulative_actual,
                "quarter_cumulative_predicted_return_pct": (
                    quarter_cumulative_predicted
                ),
                "quarter_cumulative_actual_minus_predicted_pct": (
                    quarter_cumulative_difference
                ),
                "quarter_cumulative_observation_count": quarter_observation_count,
                "status": _worst_status(item.consistency.status for item in fund_results),
                "coverage_pct": coverage_pct,
            }
        )
    rows.sort(
        key=lambda item: (
            -Decimal(str(item["portfolio_weight_pct"])),
            item["representative_code"],
        )
    )
    return tuple(rows)


def _common_cumulative_points(
    prediction_series: tuple[tuple[DailyPrediction, ...], ...],
    comparison_nav_date: date,
) -> tuple[list[CumulativePoint], int] | None:
    paired_date_sets = [
        {
            item.nav_date
            for item in predictions
            if item.nav_date <= comparison_nav_date
            and item.actual_return_pct is not None
            and item.predicted_return_pct is not None
        }
        for predictions in prediction_series
    ]
    common_dates = set.intersection(*paired_date_sets) if paired_date_sets else set()
    if comparison_nav_date not in common_dates:
        return None
    points: list[CumulativePoint] = []
    for predictions in prediction_series:
        common_predictions = [item for item in predictions if item.nav_date in common_dates]
        point = next(reversed(cumulative_points(common_predictions)), None)
        if (
            point is None
            or point.cumulative_actual_return_pct is None
            or point.cumulative_predicted_return_pct is None
        ):
            return None
        points.append(point)
    return points, len(common_dates)


def _weighted_allocations(
    session: Session,
    results: tuple[FundAnalysisResult, ...],
    contract_weights: dict[int, Decimal],
    *,
    allocation_type: str,
) -> tuple[dict[str, Any], ...]:
    report_by_fund = {item.target.fund_id: item.target.report_id for item in results}
    totals: dict[str, Decimal] = defaultdict(Decimal)
    if allocation_type == "country":
        rows = session.execute(
            select(
                ReportCountryAllocation.fund_report_id,
                ReportCountryAllocation.country_name_normalized,
                ReportCountryAllocation.nav_pct,
            ).where(
                ReportCountryAllocation.fund_report_id.in_(report_by_fund.values()),
                ReportCountryAllocation.exposure_basis == "DIRECT",
                ReportCountryAllocation.nav_pct.is_not(None),
            )
        ).all()
    else:
        rows = session.execute(
            select(
                ReportIndustryAllocation.fund_report_id,
                ReportIndustryAllocation.industry_name_normalized,
                ReportIndustryAllocation.nav_pct,
            ).where(
                ReportIndustryAllocation.fund_report_id.in_(report_by_fund.values()),
                ReportIndustryAllocation.exposure_basis == "DIRECT",
                ReportIndustryAllocation.nav_pct.is_not(None),
            )
        ).all()
    fund_by_report = {report_id: fund_id for fund_id, report_id in report_by_fund.items()}
    aliases = (
        COUNTRY_EXPOSURE_ALIASES
        if allocation_type == "country"
        else INDUSTRY_EXPOSURE_ALIASES
    )
    for report_id, name, nav_pct in rows:
        if nav_pct is not None:
            canonical_name = aliases.get(_exposure_alias_key(name), name.strip())
            totals[canonical_name] += (
                contract_weights[fund_by_report[report_id]] * nav_pct
            )
    if allocation_type == "industry":
        semiconductor_rows = session.execute(
            select(
                ReportDerivedMetrics.fund_report_id,
                ReportDerivedMetrics.semiconductor_top10_pct,
            ).where(
                ReportDerivedMetrics.fund_report_id.in_(report_by_fund.values()),
                ReportDerivedMetrics.semiconductor_top10_pct.is_not(None),
            )
        ).all()
        for report_id, semiconductor_top10_pct in semiconductor_rows:
            if semiconductor_top10_pct is not None:
                totals[SEMICONDUCTOR_TOP10_LABEL] += (
                    contract_weights[fund_by_report[report_id]]
                    * semiconductor_top10_pct
                )
    return tuple(
        {"name": name, "portfolio_exposure_pct": _q(value)}
        for name, value in sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    )


def _exposure_alias_key(name: str) -> str:
    return name.strip().upper().replace("-", "_").replace(" ", "_")


def _portfolio_overlaps(
    session: Session, results: tuple[FundAnalysisResult, ...]
) -> tuple[dict[str, Any], ...]:
    unique: dict[int, FundAnalysisResult] = {}
    for result in results:
        unique.setdefault(result.target.fund_id, result)
    holdings_by_fund: dict[int, dict[str, tuple[str, Decimal]]] = {}
    for fund_id, result in unique.items():
        rows = session.scalars(
            select(ReportSecurityHolding).where(
                ReportSecurityHolding.fund_report_id == result.target.report_id,
                ReportSecurityHolding.exposure_basis == "DIRECT",
                ReportSecurityHolding.nav_pct.is_not(None),
                ReportSecurityHolding.nav_pct > 0,
            )
        ).all()
        mapped = {}
        for row in rows:
            mapping = map_security_holding(row)
            key = mapping.provider_symbol or (
                f"RAW:{row.security_code_raw}"
                if row.security_code_raw
                else f"NAME:{row.security_name_normalized.casefold()}"
            )
            mapped[key] = (row.security_name_normalized, row.nav_pct or Decimal("0"))
        holdings_by_fund[fund_id] = mapped
    fund_ids = sorted(unique)
    overlaps = []
    for left_index, left_id in enumerate(fund_ids):
        for right_id in fund_ids[left_index + 1 :]:
            left = holdings_by_fund[left_id]
            right = holdings_by_fund[right_id]
            common = []
            for key in sorted(left.keys() & right.keys()):
                left_name, left_weight = left[key]
                right_name, right_weight = right[key]
                common.append(
                    {
                        "symbol": key.removeprefix("RAW:").removeprefix("NAME:"),
                        "security_name": left_name or right_name,
                        "left_weight_pct": left_weight,
                        "right_weight_pct": right_weight,
                        "overlap_weight_pct": min(left_weight, right_weight),
                    }
                )
            if common:
                common.sort(key=lambda item: -Decimal(str(item["overlap_weight_pct"])))
                overlaps.append(
                    {
                        "left_fund_id": left_id,
                        "left_fund_name": unique[left_id].target.fund_name,
                        "right_fund_id": right_id,
                        "right_fund_name": unique[right_id].target.fund_name,
                        "overlap_weight_pct": _q(
                            sum(
                                (
                                    Decimal(str(item["overlap_weight_pct"]))
                                    for item in common
                                ),
                                start=Decimal("0"),
                            )
                        ),
                        "securities": common,
                    }
                )
    overlaps.sort(key=lambda item: -Decimal(str(item["overlap_weight_pct"])))
    return tuple(overlaps)


def _proxy_payload(config: FundProxyConfig | None) -> list[dict[str, Any]]:
    if config is None:
        return []
    return [
        {
            "symbol": item.symbol,
            "currency": item.currency,
            "weight": item.weight,
            "reason": config.reason,
            "confidence": config.confidence,
        }
        for item in config.proxies
    ]


def _unique_sources(sources: Any) -> tuple[AnalysisSource, ...]:
    result = []
    seen = set()
    for item in sources:
        key = (item.source_type, item.provider, item.url, item.data_date)
        if key not in seen:
            result.append(item)
            seen.add(key)
    return tuple(result)


def _worst_status(statuses: Any) -> str:
    order = {
        "LIKELY_EXPOSURE_CHANGED": 4,
        "SLIGHTLY_DIVERGING": 3,
        "INSUFFICIENT_DATA": 2,
        "CONSISTENT": 1,
        "NOT_APPLICABLE": 0,
    }
    return max(statuses, key=lambda item: order.get(item, -1))


def _latest_comparable_nav_date(as_of: date) -> date:
    display_date = as_of
    while display_date.weekday() >= 5:
        display_date -= timedelta(days=1)
    nav_date = display_date - timedelta(days=1)
    while nav_date.weekday() >= 5:
        nav_date -= timedelta(days=1)
    return nav_date


def _next_weekday(value: date) -> date:
    result = value + timedelta(days=1)
    while result.weekday() >= 5:
        result += timedelta(days=1)
    return result


def _sum_decimal(values: Any) -> Decimal:
    return sum((value for value in values if value is not None), start=Decimal("0"))


def _currency_matches(expected: str, actual: str) -> bool:
    normalized_actual = actual.strip().upper()
    if expected.upper() == "GBP" and normalized_actual == "GBP":
        return True
    return expected.upper() == normalized_actual


def _q(value: Decimal) -> Decimal:
    return value.quantize(PCT_SCALE, rounding=ROUND_HALF_UP)
