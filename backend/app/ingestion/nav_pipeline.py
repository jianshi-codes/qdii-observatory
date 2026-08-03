"""Idempotent NAV and exchange-price archival pipelines."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ingestion.archive import archive_bytes
from backend.app.ingestion.providers.base import MarketPriceProvider, NavProvider, NavRecord
from backend.app.ingestion.runs import finish_run, record_issue, resolve_issues, start_run
from backend.app.models import (
    DailyExchangePrice,
    DailyFundNav,
    FundShare,
    IngestionRun,
    SourceArtifact,
)

NAV_RETURN_TOLERANCE_PCT = Decimal(os.getenv("QDII_NAV_RETURN_TOLERANCE_PCT", "0.02"))


def sync_nav(
    session: Session,
    provider: NavProvider,
    raw_root: Path,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    share_codes: set[str] | None = None,
    page_size: int = 20,
) -> IngestionRun:
    run = start_run(
        session,
        "sync_nav",
        {
            "provider": provider.name,
            "version": provider.version,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "page_size": page_size,
        },
    )
    shares = list(
        session.scalars(
            select(FundShare)
            .join(FundShare.fund_contract)
            .where(FundShare.fund_contract.has(is_user_selected=True))
            .order_by(FundShare.share_code)
        )
    )
    if share_codes is not None:
        shares = [share for share in shares if share.share_code in share_codes]
    total_written = failed = 0
    for share in shares:
        try:
            records: list[NavRecord] = []
            payload_hash_by_date: dict[date, str] = {}
            page_index = 1
            total_pages = 1
            while page_index <= total_pages:
                page = provider.fetch_page(
                    share.share_code,
                    page_index,
                    page_size,
                    start_date=start_date,
                    end_date=end_date,
                )
                total_pages = page.total_pages
                digest = hashlib.sha256(page.raw_payload).hexdigest()
                artifact = archive_bytes(
                    raw_root,
                    Path("nav") / provider.name.lower() / share.share_code,
                    f"page-{page_index:04d}",
                    ".js" if "javascript" in page.mime_type else ".json",
                    page.raw_payload,
                )
                _record_artifact(
                    session,
                    run,
                    share,
                    artifact.path.relative_to(raw_root.resolve()),
                    artifact.sha256,
                    artifact.byte_size,
                    artifact.fetched_at,
                    page.source_url,
                    page.mime_type,
                    {"provider_version": page.provider_version, "page_index": page_index},
                )
                records.extend(page.records)
                payload_hash_by_date.update({row.nav_date: digest for row in page.records})
                page_index += 1
            if not records:
                raise ValueError(
                    f"NAV provider returned no records for {share.share_code} "
                    "in the requested range"
                )
            resolve_issues(
                session,
                issue_codes=("NAV_SYNC_FAILED", "NAV_RETURN_MISMATCH"),
                fund_contract_id=share.fund_contract_id,
                fund_share_id=share.id,
            )
            total_written += _upsert_nav_rows(
                session,
                run,
                share,
                provider.name,
                records,
                payload_hash_by_date,
            )
        except Exception as error:
            failed += 1
            record_issue(
                session,
                ingestion_run_id=run.id,
                fund_contract_id=share.fund_contract_id,
                fund_share_id=share.id,
                issue_code="NAV_SYNC_FAILED",
                severity="ERROR",
                message=f"NAV sync failed for {share.share_code}: {error}",
                details={"provider": provider.name, "exception_type": type(error).__name__},
            )
        session.commit()
    finish_run(
        run,
        status="succeeded" if failed == 0 else "partial",
        seen=len(shares),
        written=total_written,
        failed=failed,
    )
    session.commit()
    return run


def _upsert_nav_rows(
    session: Session,
    run: IngestionRun,
    share: FundShare,
    provider_name: str,
    records: list[NavRecord],
    payload_hash_by_date: dict[date, str],
) -> int:
    if not records:
        return 0
    by_date = {record.nav_date: record for record in records}
    ordered = [by_date[key] for key in sorted(by_date)]
    existing = {
        row.nav_date: row
        for row in session.scalars(
            select(DailyFundNav).where(
                DailyFundNav.fund_share_id == share.id,
                DailyFundNav.source_provider == provider_name,
                DailyFundNav.nav_date.in_(list(by_date)),
            )
        )
    }
    previous = session.scalar(
        select(DailyFundNav)
        .where(
            DailyFundNav.fund_share_id == share.id,
            DailyFundNav.source_provider == provider_name,
            DailyFundNav.nav_date < ordered[0].nav_date,
        )
        .order_by(DailyFundNav.nav_date.desc())
        .limit(1)
    )
    previous_nav = previous.unit_nav if previous is not None else None
    now = datetime.now(UTC)
    for record in ordered:
        calculated = (
            (record.unit_nav / previous_nav - Decimal("1")) * Decimal("100")
            if previous_nav is not None
            else None
        )
        row = existing.get(record.nav_date)
        if row is None:
            row = DailyFundNav(
                fund_share_id=share.id,
                nav_date=record.nav_date,
                source_provider=provider_name,
                raw_payload_hash=payload_hash_by_date[record.nav_date],
            )
            session.add(row)
        row.unit_nav = record.unit_nav
        row.accumulated_nav = record.accumulated_nav
        row.published_daily_return_pct = record.published_daily_return_pct
        row.calculated_daily_return_pct = calculated
        row.source_published_at = record.source_published_at
        row.fetched_at = now
        row.raw_payload_hash = payload_hash_by_date[record.nav_date]
        if (
            calculated is not None
            and record.published_daily_return_pct is not None
            and abs(calculated - record.published_daily_return_pct) > NAV_RETURN_TOLERANCE_PCT
        ):
            record_issue(
                session,
                ingestion_run_id=run.id,
                fund_contract_id=share.fund_contract_id,
                fund_share_id=share.id,
                issue_code="NAV_RETURN_MISMATCH",
                severity="WARNING",
                message=f"Published and calculated NAV returns differ on {record.nav_date}",
                details={
                    "nav_date": record.nav_date.isoformat(),
                    "published_pct": str(record.published_daily_return_pct),
                    "calculated_pct": str(calculated),
                    "tolerance_pct": str(NAV_RETURN_TOLERANCE_PCT),
                    "review": "Check dividend, split, conversion, and source revision events.",
                },
            )
        previous_nav = record.unit_nav
    session.flush()
    return len(ordered)


def sync_exchange_prices(
    session: Session,
    provider: MarketPriceProvider,
    raw_root: Path,
    *,
    start_date: date,
    end_date: date,
    share_codes: set[str] | None = None,
) -> IngestionRun:
    run = start_run(
        session,
        "sync_exchange_prices",
        {
            "provider": provider.name,
            "version": provider.version,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    shares = list(
        session.scalars(
            select(FundShare)
            .where(FundShare.is_exchange_traded.is_(True))
            .order_by(FundShare.share_code)
        )
    )
    if share_codes is not None:
        shares = [share for share in shares if share.share_code in share_codes]
    written = failed = 0
    for share in shares:
        try:
            raw, records, source_url = provider.fetch(share.share_code, start_date, end_date)
            if not records:
                raise ValueError(
                    f"Market provider returned no records for {share.share_code} "
                    "in the requested range"
                )
            artifact = archive_bytes(
                raw_root,
                Path("market") / provider.name.lower() / share.share_code,
                f"{start_date.isoformat()}-{end_date.isoformat()}",
                ".json",
                raw,
            )
            _record_artifact(
                session,
                run,
                share,
                artifact.path.relative_to(raw_root.resolve()),
                artifact.sha256,
                artifact.byte_size,
                artifact.fetched_at,
                source_url,
                "application/json",
                {"provider_version": provider.version},
            )
            existing = {
                row.trade_date: row
                for row in session.scalars(
                    select(DailyExchangePrice).where(
                        DailyExchangePrice.fund_share_id == share.id,
                        DailyExchangePrice.source_provider == provider.name,
                        DailyExchangePrice.trade_date.in_([item.trade_date for item in records]),
                    )
                )
            }
            nav_by_date = {
                row.nav_date: row
                for row in session.scalars(
                    select(DailyFundNav).where(
                        DailyFundNav.fund_share_id == share.id,
                        DailyFundNav.nav_date.in_([item.trade_date for item in records]),
                    )
                )
            }
            for item in records:
                row = existing.get(item.trade_date)
                if row is None:
                    row = DailyExchangePrice(
                        fund_share_id=share.id,
                        trade_date=item.trade_date,
                        source_provider=provider.name,
                    )
                    session.add(row)
                nav = nav_by_date.get(item.trade_date)
                row.open = item.open
                row.high = item.high
                row.low = item.low
                row.close = item.close
                row.pct_change = item.pct_change
                row.volume = item.volume
                row.turnover = item.turnover
                row.fetched_at = datetime.now(UTC)
                row.corresponding_nav_date = nav.nav_date if nav else None
                row.premium_discount_pct = (
                    (item.close / nav.unit_nav - Decimal("1")) * Decimal("100")
                    if nav is not None
                    else None
                )
            resolve_issues(
                session,
                issue_codes=("MARKET_PRICE_SYNC_FAILED",),
                fund_contract_id=share.fund_contract_id,
                fund_share_id=share.id,
            )
            written += len(records)
        except Exception as error:
            failed += 1
            record_issue(
                session,
                ingestion_run_id=run.id,
                fund_contract_id=share.fund_contract_id,
                fund_share_id=share.id,
                issue_code="MARKET_PRICE_SYNC_FAILED",
                severity="ERROR",
                message=f"Market price sync failed for {share.share_code}: {error}",
                details={"provider": provider.name, "exception_type": type(error).__name__},
            )
        session.commit()
    finish_run(
        run,
        status="succeeded" if failed == 0 else "partial",
        seen=len(shares),
        written=written,
        failed=failed,
    )
    session.commit()
    return run


def sync_daily(
    session: Session,
    nav_provider: NavProvider,
    market_provider: MarketPriceProvider,
    raw_root: Path,
    *,
    lookback_days: int = 10,
    share_codes: set[str] | None = None,
) -> tuple[IngestionRun, IngestionRun]:
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    nav_run = sync_nav(
        session,
        nav_provider,
        raw_root,
        start_date=start_date,
        end_date=end_date,
        share_codes=share_codes,
    )
    market_run = sync_exchange_prices(
        session,
        market_provider,
        raw_root,
        start_date=start_date,
        end_date=end_date,
        share_codes=share_codes,
    )
    return nav_run, market_run


def _record_artifact(
    session: Session,
    run: IngestionRun,
    share: FundShare,
    local_path: Path,
    sha256: str,
    byte_size: int,
    fetched_at: datetime,
    source_url: str,
    mime_type: str,
    metadata: dict[str, object],
) -> None:
    exists = session.scalar(
        select(SourceArtifact.id).where(
            SourceArtifact.source_provider == metadata.get("provider", run.parameters["provider"]),
            SourceArtifact.sha256 == sha256,
        )
    )
    if exists is not None:
        return
    session.add(
        SourceArtifact(
            ingestion_run_id=run.id,
            fund_contract_id=share.fund_contract_id,
            fund_share_id=share.id,
            artifact_type=(
                "NAV_JAVASCRIPT"
                if run.job_type == "sync_nav" and "javascript" in mime_type
                else "NAV_JSON"
                if run.job_type == "sync_nav"
                else "MARKET_JSON"
            ),
            source_provider=str(run.parameters["provider"]),
            source_url=source_url,
            local_path=str(local_path),
            mime_type=mime_type,
            sha256=sha256,
            byte_size=byte_size,
            fetched_at=fetched_at,
            metadata_json=metadata,
        )
    )
