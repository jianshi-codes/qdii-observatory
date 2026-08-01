"""Transparent weighted look-through with unresolved and circular-path accounting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.ingestion.runs import record_issue
from backend.app.models import (
    FundReport,
    ReportCountryAllocation,
    ReportDerivedMetrics,
    ReportFundHolding,
    ReportIndustryAllocation,
)


@dataclass(frozen=True, slots=True)
class HoldingEdge[NodeId]:
    target: NodeId | None
    weight_pct: Decimal


@dataclass(frozen=True, slots=True)
class ExposureNode[NodeId]:
    direct: dict[str, Decimal]
    holdings: tuple[HoldingEdge[NodeId], ...]


@dataclass(frozen=True, slots=True)
class LookthroughResult:
    exposure: dict[str, Decimal]
    coverage_pct: Decimal
    unresolved_fund_weight_pct: Decimal
    max_depth: int
    circular_relation_detected: bool


def weighted_lookthrough[NodeId](
    nodes: dict[NodeId, ExposureNode[NodeId]], root: NodeId, max_depth: int = 5
) -> LookthroughResult:
    """Resolve a graph where all values and weights are percentage points."""

    def visit(node_id: NodeId, path: tuple[NodeId, ...], depth: int) -> LookthroughResult:
        if node_id in path:
            return LookthroughResult({}, Decimal("0"), Decimal("100"), depth, True)
        node = nodes.get(node_id)
        if node is None:
            return LookthroughResult({}, Decimal("0"), Decimal("100"), depth, False)
        exposure = dict(node.direct)
        coverage = min(Decimal("100"), sum(node.direct.values(), Decimal("0")))
        unresolved = Decimal("0")
        deepest = depth
        circular = False
        for edge in node.holdings:
            if edge.weight_pct <= 0:
                continue
            if edge.target is None or depth >= max_depth:
                unresolved += edge.weight_pct
                deepest = max(deepest, depth)
                continue
            child = visit(edge.target, (*path, node_id), depth + 1)
            for label, child_weight in child.exposure.items():
                exposure[label] = exposure.get(label, Decimal("0")) + (
                    edge.weight_pct * child_weight / Decimal("100")
                )
            nested_unresolved = edge.weight_pct * child.unresolved_fund_weight_pct / Decimal("100")
            unresolved += nested_unresolved
            coverage += max(Decimal("0"), edge.weight_pct - nested_unresolved)
            deepest = max(deepest, child.max_depth)
            circular = circular or child.circular_relation_detected
        return LookthroughResult(
            exposure=exposure,
            coverage_pct=min(Decimal("100"), coverage),
            unresolved_fund_weight_pct=min(Decimal("100"), unresolved),
            max_depth=deepest,
            circular_relation_detected=circular,
        )

    return visit(root, (), 0)


def calculate_and_store_lookthrough(
    session: Session, *, year: int, quarter: int, max_depth: int = 5
) -> dict[int, LookthroughResult]:
    reports = list(
        session.scalars(
            select(FundReport).where(
                FundReport.report_type == "QUARTERLY",
                FundReport.report_year == year,
                FundReport.report_quarter == quarter,
                FundReport.parse_status == "parsed",
            )
        )
    )
    report_by_contract = {report.fund_contract_id: report for report in reports}
    country_nodes = _build_nodes(session, reports, report_by_contract, ReportCountryAllocation)
    industry_nodes = _build_nodes(session, reports, report_by_contract, ReportIndustryAllocation)
    results: dict[int, LookthroughResult] = {}
    for report in reports:
        country = weighted_lookthrough(country_nodes, report.id, max_depth=max_depth)
        industry = weighted_lookthrough(industry_nodes, report.id, max_depth=max_depth)
        _store_rows(session, report, country, ReportCountryAllocation)
        _store_rows(session, report, industry, ReportIndustryAllocation)
        metrics = session.scalar(
            select(ReportDerivedMetrics).where(ReportDerivedMetrics.fund_report_id == report.id)
        )
        if metrics is not None:
            metrics.lookthrough_coverage_pct = country.coverage_pct
            metrics.unresolved_fund_weight_pct = max(
                country.unresolved_fund_weight_pct, industry.unresolved_fund_weight_pct
            )
            metrics.max_lookthrough_depth = max(country.max_depth, industry.max_depth)
            metrics.circular_relation_detected = (
                country.circular_relation_detected or industry.circular_relation_detected
            )
        if country.circular_relation_detected or industry.circular_relation_detected:
            record_issue(
                session,
                fund_contract_id=report.fund_contract_id,
                fund_report_id=report.id,
                issue_code="LOOKTHROUGH_CYCLE",
                severity="ERROR",
                message="Circular report fund relation detected; the affected path was stopped.",
                details={"max_depth": max(country.max_depth, industry.max_depth)},
            )
        results[report.id] = country
    session.flush()
    return results


def _build_nodes(
    session: Session,
    reports: list[FundReport],
    report_by_contract: dict[int, FundReport],
    allocation_model: type[ReportCountryAllocation] | type[ReportIndustryAllocation],
) -> dict[int, ExposureNode[int]]:
    nodes: dict[int, ExposureNode[int]] = {}
    for report in reports:
        rows = session.scalars(
            select(allocation_model).where(
                allocation_model.fund_report_id == report.id,
                allocation_model.exposure_basis == "DIRECT",
            )
        )
        label_attribute = (
            "country_name_normalized"
            if allocation_model is ReportCountryAllocation
            else "industry_name_normalized"
        )
        direct: dict[str, Decimal] = {}
        for row in rows:
            allocation = cast(ReportCountryAllocation | ReportIndustryAllocation, row)
            if allocation.nav_pct is not None:
                label = getattr(allocation, label_attribute)
                direct[label] = direct.get(label, Decimal("0")) + allocation.nav_pct
        edges: list[HoldingEdge[int]] = []
        holdings = session.scalars(
            select(ReportFundHolding).where(
                ReportFundHolding.fund_report_id == report.id,
                ReportFundHolding.exposure_basis == "DIRECT",
            )
        )
        for holding in holdings:
            target_report = (
                report_by_contract.get(holding.resolved_fund_contract_id)
                if holding.resolved_fund_contract_id is not None
                else None
            )
            edges.append(
                HoldingEdge(
                    target=target_report.id if target_report is not None else None,
                    weight_pct=holding.nav_pct or Decimal("0"),
                )
            )
        nodes[report.id] = ExposureNode(direct=direct, holdings=tuple(edges))
    return nodes


def _store_rows(
    session: Session,
    report: FundReport,
    result: LookthroughResult,
    model: type[ReportCountryAllocation] | type[ReportIndustryAllocation],
) -> None:
    session.execute(
        delete(model).where(
            model.fund_report_id == report.id,
            model.exposure_basis == "LOOKTHROUGH",
        )
    )
    for rank, (label, weight) in enumerate(
        sorted(result.exposure.items(), key=lambda item: (-item[1], item[0])), start=1
    ):
        common = {
            "fund_report_id": report.id,
            "fair_value_cny": None,
            "nav_pct": weight,
            "rank": rank,
            "source_section": "calculated look-through exposure",
            "raw_row": {
                "formula": "direct + sum(underlying_fund_weight * underlying_exposure / 100)",
                "max_depth": result.max_depth,
            },
            "parse_confidence": Decimal("0.90"),
            "exposure_basis": "LOOKTHROUGH",
        }
        if model is ReportCountryAllocation:
            session.add(
                ReportCountryAllocation(
                    country_name_raw=label,
                    country_name_normalized=label,
                    **common,
                )
            )
        else:
            session.add(
                ReportIndustryAllocation(
                    industry_name_raw=label,
                    industry_name_normalized=label,
                    **common,
                )
            )
