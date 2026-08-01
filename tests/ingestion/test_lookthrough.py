from __future__ import annotations

from decimal import Decimal

from backend.app.ingestion.lookthrough import ExposureNode, HoldingEdge, weighted_lookthrough


def test_weighted_lookthrough_combines_direct_and_underlying_exposure() -> None:
    nodes = {
        "root": ExposureNode(
            direct={"CN": Decimal("20")},
            holdings=(HoldingEdge(target="underlying", weight_pct=Decimal("80")),),
        ),
        "underlying": ExposureNode(
            direct={"US": Decimal("75"), "TW": Decimal("25")},
            holdings=(),
        ),
    }

    result = weighted_lookthrough(nodes, "root")

    assert result.exposure == {
        "CN": Decimal("20"),
        "US": Decimal("60"),
        "TW": Decimal("20"),
    }
    assert result.coverage_pct == Decimal("100")
    assert result.unresolved_fund_weight_pct == Decimal("0")
    assert result.max_depth == 1
    assert result.circular_relation_detected is False


def test_weighted_lookthrough_stops_cycle_and_accounts_for_unresolved_weight() -> None:
    nodes = {
        "a": ExposureNode(
            direct={},
            holdings=(HoldingEdge(target="b", weight_pct=Decimal("50")),),
        ),
        "b": ExposureNode(
            direct={},
            holdings=(HoldingEdge(target="a", weight_pct=Decimal("100")),),
        ),
    }

    result = weighted_lookthrough(nodes, "a")

    assert result.exposure == {}
    assert result.coverage_pct == Decimal("0")
    assert result.unresolved_fund_weight_pct == Decimal("50")
    assert result.max_depth == 2
    assert result.circular_relation_detected is True


def test_weighted_lookthrough_stops_at_configured_depth() -> None:
    nodes = {
        "a": ExposureNode(
            direct={},
            holdings=(HoldingEdge(target="b", weight_pct=Decimal("80")),),
        ),
        "b": ExposureNode(
            direct={},
            holdings=(HoldingEdge(target="c", weight_pct=Decimal("50")),),
        ),
        "c": ExposureNode(direct={"US": Decimal("100")}, holdings=()),
    }

    result = weighted_lookthrough(nodes, "a", max_depth=1)

    assert result.exposure == {}
    assert result.coverage_pct == Decimal("40")
    assert result.unresolved_fund_weight_pct == Decimal("40")
    assert result.max_depth == 1
    assert result.circular_relation_detected is False
