"""Configurable residual diagnostics for the static Q2 baseline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal
from math import sqrt
from typing import Any, Literal

from backend.app.q2_analysis.predictor import DailyPrediction

ConsistencyStatus = Literal[
    "CONSISTENT",
    "SLIGHTLY_DIVERGING",
    "LIKELY_EXPOSURE_CHANGED",
    "INSUFFICIENT_DATA",
    "NOT_APPLICABLE",
]
PCT_SCALE = Decimal("0.00000001")
LIKELY_CHANGED_EXPLANATION = (
    "近期基金实际收益与基于 2026 Q2 期末披露持仓的静态模型持续偏离。"
    "偏离可能来自调仓、未披露持仓、现金、基金投资、汇率时点、"
    "衍生品或其他组合因素，不能据此识别具体证券买卖。"
)


@dataclass(frozen=True, slots=True)
class ConsistencyRules:
    minimum_observations: int
    likely_minimum_observations: int
    minimum_recent_coverage_pct: Decimal
    slightly_mae_5_pct: Decimal
    slightly_abs_bias_5_pct: Decimal
    slightly_correlation: Decimal
    likely_mae_5_pct: Decimal
    likely_abs_bias_5_pct: Decimal
    likely_residual_streak: int
    likely_cumulative_residual_pct: Decimal

    @classmethod
    def from_mapping(cls, raw: dict[str, object]) -> ConsistencyRules:
        def integer(field: str) -> int:
            if field not in raw:
                raise ValueError(f"Missing consistency rule: {field}")
            value = int(str(raw[field]))
            if value < 1:
                raise ValueError(f"Consistency rule {field} must be positive")
            return value

        def decimal(field: str) -> Decimal:
            if field not in raw:
                raise ValueError(f"Missing consistency rule: {field}")
            value = Decimal(str(raw[field]))
            if value < 0:
                raise ValueError(f"Consistency rule {field} must be nonnegative")
            return value

        return cls(
            minimum_observations=integer("minimum_observations"),
            likely_minimum_observations=integer("likely_minimum_observations"),
            minimum_recent_coverage_pct=decimal("minimum_recent_coverage_pct"),
            slightly_mae_5_pct=decimal("slightly_mae_5_pct"),
            slightly_abs_bias_5_pct=decimal("slightly_abs_bias_5_pct"),
            slightly_correlation=decimal("slightly_correlation"),
            likely_mae_5_pct=decimal("likely_mae_5_pct"),
            likely_abs_bias_5_pct=decimal("likely_abs_bias_5_pct"),
            likely_residual_streak=integer("likely_residual_streak"),
            likely_cumulative_residual_pct=decimal(
                "likely_cumulative_residual_pct"
            ),
        )


@dataclass(frozen=True, slots=True)
class ConsistencyResult:
    status: ConsistencyStatus
    observation_count: int
    mae_5_pct: Decimal | None
    mae_10_pct: Decimal | None
    mae_20_pct: Decimal | None
    signed_bias_5_pct: Decimal | None
    signed_bias_10_pct: Decimal | None
    cumulative_residual_pct: Decimal | None
    actual_predicted_correlation: Decimal | None
    same_direction_residual_streak: int
    recent_coverage_pct: Decimal | None
    explanation: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CumulativePoint:
    nav_date: str
    actual_return_pct: Decimal | None
    predicted_return_pct: Decimal | None
    cumulative_actual_return_pct: Decimal | None
    cumulative_predicted_return_pct: Decimal | None
    analysis_mode: str


def evaluate_consistency(
    predictions: list[DailyPrediction],
    rules: ConsistencyRules,
    *,
    not_applicable: bool = False,
) -> ConsistencyResult:
    if not_applicable:
        return ConsistencyResult(
            status="NOT_APPLICABLE",
            observation_count=0,
            mae_5_pct=None,
            mae_10_pct=None,
            mae_20_pct=None,
            signed_bias_5_pct=None,
            signed_bias_10_pct=None,
            cumulative_residual_pct=None,
            actual_predicted_correlation=None,
            same_direction_residual_streak=0,
            recent_coverage_pct=None,
            explanation="ETF、指数基金或 ETF 联接基金不运行主动调仓偏离模型。",
        )
    ordered = sorted(predictions, key=lambda item: item.nav_date)
    paired = [
        item
        for item in ordered
        if item.actual_return_pct is not None and item.predicted_return_pct is not None
    ]
    residuals = [
        item.actual_return_pct - item.predicted_return_pct  # type: ignore[operator]
        for item in paired
    ]
    actual = [item.actual_return_pct for item in paired if item.actual_return_pct is not None]
    predicted = [
        item.predicted_return_pct for item in paired if item.predicted_return_pct is not None
    ]
    recent_coverage = _recent_coverage(ordered)
    mae_5 = _mae(residuals, 5)
    mae_10 = _mae(residuals, 10)
    mae_20 = _mae(residuals, 20)
    bias_5 = _bias(residuals, 5)
    bias_10 = _bias(residuals, 10)
    cumulative = (
        _q(sum(residuals, start=Decimal("0"))) if residuals else None
    )
    correlation = _pearson(actual, predicted)
    streak = _residual_streak(
        [
            (
                item.actual_return_pct - item.predicted_return_pct
                if item.actual_return_pct is not None
                and item.predicted_return_pct is not None
                else None
            )
            for item in ordered
        ]
    )
    status = _status(
        len(paired),
        recent_coverage,
        mae_5=mae_5,
        bias_5=bias_5,
        cumulative=cumulative,
        correlation=correlation,
        streak=streak,
        rules=rules,
    )
    explanation = {
        "CONSISTENT": "近期实际收益与 Q2 静态披露持仓基线的误差仍在配置阈值内。",
        "SLIGHTLY_DIVERGING": (
            "近期误差有所扩大，但证据不足以判断基金暴露已经发生显著变化。"
        ),
        "LIKELY_EXPOSURE_CHANGED": LIKELY_CHANGED_EXPLANATION,
        "INSUFFICIENT_DATA": "有效观测或近期解释覆盖不足，暂不判断 Q2 持仓一致性。",
        "NOT_APPLICABLE": "ETF、指数基金或 ETF 联接基金不运行主动调仓偏离模型。",
    }[status]
    return ConsistencyResult(
        status=status,
        observation_count=len(paired),
        mae_5_pct=mae_5,
        mae_10_pct=mae_10,
        mae_20_pct=mae_20,
        signed_bias_5_pct=bias_5,
        signed_bias_10_pct=bias_10,
        cumulative_residual_pct=cumulative,
        actual_predicted_correlation=correlation,
        same_direction_residual_streak=streak,
        recent_coverage_pct=recent_coverage,
        explanation=explanation,
    )


def cumulative_points(predictions: list[DailyPrediction]) -> list[CumulativePoint]:
    actual_factor = Decimal("1")
    predicted_factor = Decimal("1")
    result: list[CumulativePoint] = []
    for item in sorted(predictions, key=lambda point: point.nav_date):
        cumulative_actual = None
        cumulative_predicted = None
        if item.actual_return_pct is not None and item.predicted_return_pct is not None:
            actual_factor *= Decimal("1") + item.actual_return_pct / Decimal("100")
            predicted_factor *= Decimal("1") + item.predicted_return_pct / Decimal("100")
            cumulative_actual = _q((actual_factor - Decimal("1")) * Decimal("100"))
            cumulative_predicted = _q((predicted_factor - Decimal("1")) * Decimal("100"))
        result.append(
            CumulativePoint(
                nav_date=item.nav_date.isoformat(),
                actual_return_pct=item.actual_return_pct,
                predicted_return_pct=item.predicted_return_pct,
                cumulative_actual_return_pct=cumulative_actual,
                cumulative_predicted_return_pct=cumulative_predicted,
                analysis_mode=item.analysis_mode,
            )
        )
    return result


def _status(
    observation_count: int,
    recent_coverage: Decimal | None,
    *,
    mae_5: Decimal | None,
    bias_5: Decimal | None,
    cumulative: Decimal | None,
    correlation: Decimal | None,
    streak: int,
    rules: ConsistencyRules,
) -> ConsistencyStatus:
    if (
        observation_count < rules.minimum_observations
        or recent_coverage is None
        or recent_coverage < rules.minimum_recent_coverage_pct
    ):
        return "INSUFFICIENT_DATA"
    likely_streak = streak >= rules.likely_residual_streak and (
        (mae_5 is not None and mae_5 >= rules.likely_mae_5_pct)
        or (bias_5 is not None and abs(bias_5) >= rules.likely_abs_bias_5_pct)
    )
    likely_cumulative = (
        cumulative is not None
        and abs(cumulative) >= rules.likely_cumulative_residual_pct
        and correlation is not None
        and correlation < rules.slightly_correlation
    )
    if observation_count >= rules.likely_minimum_observations and (
        likely_streak or likely_cumulative
    ):
        return "LIKELY_EXPOSURE_CHANGED"
    if (
        (mae_5 is not None and mae_5 >= rules.slightly_mae_5_pct)
        or (bias_5 is not None and abs(bias_5) >= rules.slightly_abs_bias_5_pct)
        or (correlation is not None and correlation < rules.slightly_correlation)
    ):
        return "SLIGHTLY_DIVERGING"
    return "CONSISTENT"


def _mae(residuals: list[Decimal], window: int) -> Decimal | None:
    if len(residuals) < window:
        return None
    values = residuals[-window:]
    return _q(sum((abs(item) for item in values), start=Decimal("0")) / Decimal(window))


def _bias(residuals: list[Decimal], window: int) -> Decimal | None:
    if len(residuals) < window:
        return None
    values = residuals[-window:]
    return _q(sum(values, start=Decimal("0")) / Decimal(window))


def _pearson(left: list[Decimal], right: list[Decimal]) -> Decimal | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left, start=Decimal("0")) / Decimal(len(left))
    right_mean = sum(right, start=Decimal("0")) / Decimal(len(right))
    numerator = sum(
        ((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True)),
        start=Decimal("0"),
    )
    left_variance = sum(((item - left_mean) ** 2 for item in left), start=Decimal("0"))
    right_variance = sum(((item - right_mean) ** 2 for item in right), start=Decimal("0"))
    if left_variance == 0 or right_variance == 0:
        return None
    denominator = Decimal(str(sqrt(float(left_variance * right_variance))))
    return _q(numerator / denominator)


def _residual_streak(residuals: list[Decimal | None]) -> int:
    if not residuals or residuals[-1] is None or residuals[-1] == 0:
        return 0
    expected_positive = residuals[-1] > 0
    count = 0
    for value in reversed(residuals):
        if value is None or value == 0 or (value > 0) != expected_positive:
            break
        count += 1
    return count


def _recent_coverage(predictions: list[DailyPrediction]) -> Decimal | None:
    if not predictions:
        return None
    values = [item.coverage.total_explained_weight_pct for item in predictions[-5:]]
    return _q(sum(values, start=Decimal("0")) / Decimal(len(values)))


def _q(value: Decimal) -> Decimal:
    return value.quantize(PCT_SCALE, rounding=ROUND_HALF_UP)
