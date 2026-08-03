"""Deterministic grouping of public share codes into one fund contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from backend.app.models import (
    DataQualityIssue,
    FundContract,
    FundExposureFamily,
    FundRelation,
    FundReport,
    FundShare,
    ReportFundHolding,
    SourceArtifact,
)

CURRENCY_MARKERS = (
    "（美元现汇）",
    "(美元现汇)",
    "（美元现钞）",
    "(美元现钞)",
    "（人民币）",
    "(人民币)",
    "美元现汇",
    "美元现钞",
    "人民币",
    "美元",
)
SHARE_CLASS_AT_BOUNDARY = re.compile(
    r"(?<=[\u3400-\u9fff）)])(?:A|C|D|E|F|H|I)(?=$|[（(])",
    re.IGNORECASE,
)
REPORT_FAILURE_ISSUES = (
    "REPORT_PARSE_FAILED",
    "REPORT_SOURCE_MISSING",
    "REPORT_SYNC_FAILED",
)


@dataclass(frozen=True, slots=True)
class GroupingResult:
    contracts_before: int
    contracts_after: int
    groups_merged: int


def public_contract_key(manager_name: str, fund_name: str, wrapper_type: str | None) -> str:
    compact = re.sub(r"\s+", "", fund_name).upper()
    compact = compact.replace("(", "（").replace(")", "）")
    for marker in CURRENCY_MARKERS:
        compact = compact.replace(marker.upper().replace("(", "（").replace(")", "）"), "")
    compact = SHARE_CLASS_AT_BOUNDARY.sub("", compact)
    manager = re.sub(r"[^0-9A-Z\u3400-\u9fff]+", "", manager_name.upper())
    return f"{manager}|{(wrapper_type or 'DIRECT').upper()}|{compact}"


def matching_public_contracts(
    session: Session,
    *,
    manager_name: str,
    fund_name: str,
    wrapper_type: str | None,
) -> list[FundContract]:
    key = public_contract_key(manager_name, fund_name, wrapper_type)
    candidates = list(
        session.scalars(select(FundContract).where(FundContract.manager_name == manager_name))
    )
    return [
        contract
        for contract in candidates
        if public_contract_key(
            contract.manager_name, contract.canonical_name, contract.wrapper_type
        )
        == key
    ]


def share_priority(currency: str, share_class: str | None, code: str) -> tuple[int, int, str]:
    currency_rank = {"CNY": 0, "HKD": 1, "USD": 2}
    class_rank = {"A": 0, None: 1, "C": 2, "D": 3}
    return (
        currency_rank.get(currency, 3),
        class_rank.get(share_class, 4),
        code,
    )


def reconcile_public_fund_contracts(session: Session) -> GroupingResult:
    contracts = list(
        session.scalars(
            select(FundContract)
            .where(FundContract.is_user_selected.is_(True))
            .order_by(FundContract.id)
        )
    )
    grouped: dict[str, list[FundContract]] = {}
    for contract in contracts:
        key = public_contract_key(
            contract.manager_name, contract.canonical_name, contract.wrapper_type
        )
        grouped.setdefault(key, []).append(contract)
    merged = 0
    for values in grouped.values():
        if len(values) < 2:
            continue
        merge_contract_group(session, values)
        merged += 1
    session.commit()
    after = session.scalar(
        select(func.count(FundContract.id)).where(FundContract.is_user_selected.is_(True))
    )
    return GroupingResult(len(contracts), int(after or 0), merged)


def merge_contract_group(
    session: Session,
    contracts: list[FundContract],
) -> FundContract:
    if not contracts:
        raise ValueError("contracts must not be empty")
    if len(contracts) == 1:
        return contracts[0]
    keys = {
        public_contract_key(item.manager_name, item.canonical_name, item.wrapper_type)
        for item in contracts
    }
    if len(keys) != 1:
        raise ValueError("contracts do not share the same public grouping key")
    primary = min(contracts, key=lambda item: _representative_priority(session, item))
    duplicate_ids = {item.id for item in contracts if item.id != primary.id}
    contract_ids = {primary.id, *duplicate_ids}

    _merge_reports(session, primary.id, contract_ids)
    session.execute(
        update(FundShare)
        .where(FundShare.fund_contract_id.in_(duplicate_ids))
        .values(fund_contract_id=primary.id)
    )
    session.execute(
        update(SourceArtifact)
        .where(SourceArtifact.fund_contract_id.in_(duplicate_ids))
        .values(fund_contract_id=primary.id)
    )
    session.execute(
        update(DataQualityIssue)
        .where(DataQualityIssue.fund_contract_id.in_(duplicate_ids))
        .values(fund_contract_id=primary.id)
    )
    session.execute(
        update(ReportFundHolding)
        .where(ReportFundHolding.resolved_fund_contract_id.in_(duplicate_ids))
        .values(resolved_fund_contract_id=primary.id)
    )
    session.execute(
        update(FundRelation)
        .where(FundRelation.source_fund_contract_id.in_(duplicate_ids))
        .values(source_fund_contract_id=primary.id)
    )
    session.execute(
        update(FundRelation)
        .where(FundRelation.target_fund_contract_id.in_(duplicate_ids))
        .values(target_fund_contract_id=primary.id)
    )
    session.execute(
        delete(FundExposureFamily).where(FundExposureFamily.fund_contract_id.in_(duplicate_ids))
    )
    session.execute(delete(FundContract).where(FundContract.id.in_(duplicate_ids)))
    primary.is_user_selected = any(item.is_user_selected for item in contracts)
    primary.is_dependency = all(item.is_dependency for item in contracts)
    session.flush()
    session.expire_all()
    persisted = session.get(FundContract, primary.id)
    if persisted is None:
        raise RuntimeError("primary fund contract disappeared during grouping")
    return persisted


def _representative_priority(session: Session, contract: FundContract) -> tuple[int, int, str]:
    share = session.scalar(
        select(FundShare).where(
            FundShare.fund_contract_id == contract.id,
            FundShare.share_code == contract.representative_code,
        )
    )
    if share is None:
        share = session.scalar(
            select(FundShare)
            .where(FundShare.fund_contract_id == contract.id)
            .order_by(FundShare.share_code)
        )
    return share_priority(
        share.currency if share else "",
        share.share_class if share else None,
        contract.representative_code,
    )


def _merge_reports(session: Session, primary_id: int, contract_ids: set[int]) -> None:
    reports = list(
        session.scalars(
            select(FundReport)
            .where(FundReport.fund_contract_id.in_(contract_ids))
            .order_by(FundReport.id)
        )
    )
    grouped: dict[tuple[str, int, int | None], list[FundReport]] = {}
    for report in reports:
        grouped.setdefault(
            (report.report_type, report.report_year, report.report_quarter), []
        ).append(report)
    for values in grouped.values():
        winner = max(
            values,
            key=lambda item: (
                _report_rank(item),
                item.fund_contract_id == primary_id,
                item.local_document_path is not None,
                -item.id,
            ),
        )
        for loser in values:
            if loser.id == winner.id:
                continue
            session.execute(
                update(SourceArtifact)
                .where(SourceArtifact.fund_report_id == loser.id)
                .values(fund_report_id=winner.id, fund_contract_id=primary_id)
            )
            session.execute(
                update(DataQualityIssue)
                .where(DataQualityIssue.fund_report_id == loser.id)
                .values(
                    fund_report_id=None,
                    fund_contract_id=primary_id,
                    status="RESOLVED",
                    resolved_at=datetime.now(UTC),
                )
            )
            session.execute(
                update(FundRelation)
                .where(FundRelation.report_id == loser.id)
                .values(report_id=winner.id)
            )
            session.execute(
                delete(FundExposureFamily).where(FundExposureFamily.fund_report_id == loser.id)
            )
            session.execute(delete(FundReport).where(FundReport.id == loser.id))
        winner.fund_contract_id = primary_id
        session.execute(
            update(DataQualityIssue)
            .where(
                DataQualityIssue.fund_report_id == winner.id,
                DataQualityIssue.issue_code.in_(REPORT_FAILURE_ISSUES),
                DataQualityIssue.status == "OPEN",
            )
            .values(status="RESOLVED", resolved_at=datetime.now(UTC))
        )
        session.flush()


def _report_rank(report: FundReport) -> int:
    return {
        "parsed": 4,
        "valid_empty": 4,
        "downloaded": 3,
        "unresolved": 2,
        "failed_with_reason": 1,
    }.get(report.parse_status.lower(), 0)
