"""Idempotent daily snapshots for direct and distributor purchase limits."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ingestion.archive import archive_bytes
from backend.app.ingestion.providers.base import (
    PurchaseLimitProvider,
    PurchaseLimitRecord,
    PurchaseLimitSnapshot,
)
from backend.app.ingestion.runs import finish_run, record_issue, resolve_issues, start_run
from backend.app.models import (
    DailyPurchaseLimit,
    FundContract,
    FundShare,
    IngestionRun,
    SourceArtifact,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
SALES_LIMIT_ISSUES = (
    "SALES_LIMIT_SYNC_FAILED",
    "SALES_LIMIT_COVERAGE_INCOMPLETE",
    "SALES_LIMIT_CHANNEL_SCOPE_AMBIGUOUS",
)


class ContractPurchaseLimitProvider(Protocol):
    name: str
    version: str

    def fetch(
        self,
        fund_code: str,
        share_codes: tuple[str, ...],
        *,
        exchange_traded_codes: frozenset[str] = frozenset(),
        share_currencies: dict[str, str] | None = None,
    ) -> PurchaseLimitSnapshot: ...


def sync_purchase_limits(
    session: Session,
    direct_provider: ContractPurchaseLimitProvider,
    distribution_provider: PurchaseLimitProvider,
    raw_root: Path,
    *,
    fund_codes: set[str] | None = None,
) -> IngestionRun:
    """Capture today's real observations; callers cannot invent a historical snapshot date."""

    run = start_run(
        session,
        "sync_sales_limits",
        {
            "direct_provider": direct_provider.name,
            "direct_provider_version": direct_provider.version,
            "distribution_provider": distribution_provider.name,
            "distribution_provider_version": distribution_provider.version,
            "timezone": "Asia/Shanghai",
        },
    )
    session.commit()
    funds = list(
        session.scalars(
            select(FundContract)
            .where(FundContract.is_user_selected.is_(True))
            .order_by(FundContract.representative_code)
        ).all()
    )
    if fund_codes is not None:
        funds = [fund for fund in funds if fund.representative_code in fund_codes]
    shares = [
        share for fund in funds for share in sorted(fund.shares, key=lambda item: item.share_code)
    ]
    failures_by_share: dict[int, list[dict[str, str]]] = defaultdict(list)
    written = failed_calls = 0

    for fund in funds:
        fund_shares = sorted(fund.shares, key=lambda item: item.share_code)
        try:
            snapshot = direct_provider.fetch(
                fund.representative_code,
                tuple(share.share_code for share in fund_shares),
                exchange_traded_codes=frozenset(
                    share.share_code for share in fund_shares if share.is_exchange_traded
                ),
                share_currencies={share.share_code: share.currency for share in fund_shares},
            )
            written += _store_snapshot(
                session,
                run,
                raw_root,
                snapshot,
                fund,
                {share.share_code: share for share in fund_shares},
                archive_key=fund.representative_code,
                artifact_share=None,
            )
            session.commit()
        except Exception as error:
            session.rollback()
            failed_calls += 1
            for share in fund_shares:
                failures_by_share[share.id].append(
                    {
                        "provider": direct_provider.name,
                        "exception_type": type(error).__name__,
                        "message": str(error),
                    }
                )

    for share in shares:
        try:
            snapshot = distribution_provider.fetch(share.share_code)
            written += _store_snapshot(
                session,
                run,
                raw_root,
                snapshot,
                share.fund_contract,
                {share.share_code: share},
                archive_key=share.share_code,
                artifact_share=share,
            )
            session.commit()
        except Exception as error:
            session.rollback()
            failed_calls += 1
            failures_by_share[share.id].append(
                {
                    "provider": distribution_provider.name,
                    "exception_type": type(error).__name__,
                    "message": str(error),
                }
            )

    snapshot_dates = list(
        session.scalars(
            select(DailyPurchaseLimit.snapshot_date)
            .where(DailyPurchaseLimit.fund_share_id.in_([share.id for share in shares]))
            .distinct()
            .order_by(DailyPurchaseLimit.snapshot_date.desc())
            .limit(1)
        ).all()
    )
    latest_snapshot_date = snapshot_dates[0] if snapshot_dates else None
    for share in shares:
        failures = failures_by_share.get(share.id, [])
        if failures:
            record_issue(
                session,
                ingestion_run_id=run.id,
                fund_contract_id=share.fund_contract_id,
                fund_share_id=share.id,
                issue_code="SALES_LIMIT_SYNC_FAILED",
                severity="ERROR",
                message=f"Sales-limit sync failed for {share.share_code}",
                details={"failures": failures},
            )
        else:
            resolve_issues(
                session,
                issue_codes=("SALES_LIMIT_SYNC_FAILED",),
                fund_contract_id=share.fund_contract_id,
                fund_share_id=share.id,
            )
        _audit_share_coverage(session, run, share, latest_snapshot_date)
        session.commit()

    finish_run(
        run,
        status="succeeded" if failed_calls == 0 else "partial",
        seen=len(funds) + len(shares),
        written=written,
        failed=failed_calls,
    )
    session.commit()
    return run


def _store_snapshot(
    session: Session,
    run: IngestionRun,
    raw_root: Path,
    snapshot: PurchaseLimitSnapshot,
    fund: FundContract,
    shares_by_code: dict[str, FundShare],
    *,
    archive_key: str,
    artifact_share: FundShare | None,
) -> int:
    if not snapshot.records:
        raise ValueError(f"{snapshot.provider_name} returned no purchase-limit records")
    _validate_records(snapshot.records, set(shares_by_code))
    suffix = {
        "application/pdf": ".pdf",
        "application/json": ".json",
        "text/html": ".html",
    }.get(snapshot.mime_type, ".bin")
    archived = archive_bytes(
        raw_root,
        Path("purchase-limits") / snapshot.provider_name.lower() / archive_key,
        "snapshot",
        suffix,
        snapshot.raw_payload,
    )
    artifact = session.scalar(
        select(SourceArtifact).where(
            SourceArtifact.source_provider == snapshot.provider_name,
            SourceArtifact.sha256 == archived.sha256,
        )
    )
    if artifact is None:
        artifact = SourceArtifact(
            ingestion_run_id=run.id,
            fund_contract_id=fund.id,
            fund_share_id=artifact_share.id if artifact_share else None,
            artifact_type=snapshot.artifact_type,
            source_provider=snapshot.provider_name,
            source_url=snapshot.source_url,
            local_path=str(archived.path.relative_to(raw_root.resolve())),
            mime_type=snapshot.mime_type,
            sha256=archived.sha256,
            byte_size=archived.byte_size,
            fetched_at=archived.fetched_at,
            metadata_json={
                "provider_version": snapshot.provider_version,
                "observed_at": snapshot.observed_at.isoformat(),
                "record_count": len(snapshot.records),
            },
        )
        session.add(artifact)
        session.flush()

    snapshot_date = snapshot.observed_at.astimezone(SHANGHAI).date()
    grouped: dict[int, list[PurchaseLimitRecord]] = defaultdict(list)
    for record in snapshot.records:
        grouped[shares_by_code[record.share_code].id].append(record)
    written = 0
    for share_id, records in grouped.items():
        existing_rows = list(
            session.scalars(
                select(DailyPurchaseLimit).where(
                    DailyPurchaseLimit.fund_share_id == share_id,
                    DailyPurchaseLimit.snapshot_date == snapshot_date,
                    DailyPurchaseLimit.source_provider == snapshot.provider_name,
                )
            ).all()
        )
        existing = {_row_identity(row): row for row in existing_rows}
        current_keys: set[tuple[str, str, str, str, str]] = set()
        for record in records:
            key = _record_identity(record)
            current_keys.add(key)
            row = existing.get(key)
            if row is None:
                row = DailyPurchaseLimit(
                    fund_share_id=share_id,
                    snapshot_date=snapshot_date,
                    channel_type=record.channel_type,
                    channel_key=record.channel_key,
                    business_type=record.business_type,
                    limit_basis=record.limit_basis,
                    share_scope=record.limit_scope,
                    source_provider=snapshot.provider_name,
                )
                session.add(row)
            row.channel_name = record.channel_name
            row.availability_state = record.availability_state
            row.cap_state = record.cap_state
            row.daily_limit_amount = record.limit_amount
            row.currency = record.currency
            row.effective_from = record.effective_from
            row.effective_to = record.effective_to
            row.source_url = snapshot.source_url
            row.source_published_at = record.source_published_at
            row.fetched_at = snapshot.observed_at
            row.source_artifact_id = artifact.id
            row.raw_payload_hash = archived.sha256
            row.raw_text = record.raw_text
            row.confidence = record.confidence
            written += 1
        for key, row in existing.items():
            if key not in current_keys:
                session.delete(row)
    session.flush()
    return written


def _record_identity(record: PurchaseLimitRecord) -> tuple[str, str, str, str, str]:
    return (
        record.channel_type,
        record.channel_key,
        record.business_type,
        record.limit_basis,
        record.limit_scope,
    )


def _row_identity(row: DailyPurchaseLimit) -> tuple[str, str, str, str, str]:
    return (
        row.channel_type,
        row.channel_key,
        row.business_type,
        row.limit_basis,
        row.share_scope,
    )


def _validate_records(records: tuple[PurchaseLimitRecord, ...], expected_codes: set[str]) -> None:
    identities: set[tuple[str, str, str, str, str, str]] = set()
    for record in records:
        if record.share_code not in expected_codes:
            raise ValueError(f"Provider returned unexpected share code {record.share_code}")
        identity = (record.share_code, *_record_identity(record))
        if identity in identities:
            raise ValueError(f"Provider returned duplicate purchase-limit key {identity}")
        identities.add(identity)


def _audit_share_coverage(
    session: Session,
    run: IngestionRun,
    share: FundShare,
    snapshot_date: date | None,
) -> None:
    rows = (
        list(
            session.scalars(
                select(DailyPurchaseLimit).where(
                    DailyPurchaseLimit.fund_share_id == share.id,
                    DailyPurchaseLimit.snapshot_date == snapshot_date,
                    DailyPurchaseLimit.business_type == "PURCHASE",
                )
            ).all()
        )
        if snapshot_date is not None
        else []
    )
    channel_rows = {
        channel: [row for row in rows if row.channel_type == channel]
        for channel in ("DIRECT", "DISTRIBUTION")
    }
    missing = [channel for channel, items in channel_rows.items() if not items]
    unknown = [
        {
            "channel_type": row.channel_type,
            "channel_key": row.channel_key,
            "availability_state": row.availability_state,
            "cap_state": row.cap_state,
        }
        for row in rows
        if row.availability_state == "UNKNOWN"
        or (
            row.cap_state == "UNKNOWN"
            and row.availability_state not in {"PAUSED", "NOT_SOLD", "NOT_APPLICABLE"}
        )
    ]
    if missing or unknown:
        record_issue(
            session,
            ingestion_run_id=run.id,
            fund_contract_id=share.fund_contract_id,
            fund_share_id=share.id,
            issue_code="SALES_LIMIT_COVERAGE_INCOMPLETE",
            severity="WARNING",
            message=f"Sales-limit coverage is incomplete for {share.share_code}",
            details={
                "snapshot_date": snapshot_date.isoformat() if snapshot_date else None,
                "missing_channels": missing,
                "unknown_states": unknown,
            },
        )
    else:
        resolve_issues(
            session,
            issue_codes=("SALES_LIMIT_COVERAGE_INCOMPLETE",),
            fund_contract_id=share.fund_contract_id,
            fund_share_id=share.id,
        )

    ambiguous = [
        {
            "channel_type": row.channel_type,
            "channel_key": row.channel_key,
            "share_scope": row.share_scope,
        }
        for row in rows
        if row.cap_state == "LIMITED" and row.share_scope == "UNKNOWN"
    ]
    if ambiguous:
        record_issue(
            session,
            ingestion_run_id=run.id,
            fund_contract_id=share.fund_contract_id,
            fund_share_id=share.id,
            issue_code="SALES_LIMIT_CHANNEL_SCOPE_AMBIGUOUS",
            severity="WARNING",
            message=f"Sales-limit share scope is ambiguous for {share.share_code}",
            details={"rows": ambiguous},
        )
    else:
        resolve_issues(
            session,
            issue_codes=("SALES_LIMIT_CHANNEL_SCOPE_AMBIGUOUS",),
            fund_contract_id=share.fund_contract_id,
            fund_share_id=share.id,
        )
