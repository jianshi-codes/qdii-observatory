"""Daily, source-backed fee snapshots for shares in the local portfolio."""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ingestion.archive import archive_bytes
from backend.app.ingestion.providers.base import FundFeeObservation, FundFeeProvider
from backend.app.ingestion.runs import finish_run, record_issue, resolve_issues, start_run
from backend.app.models import (
    DailyFundFee,
    FundShare,
    IngestionRun,
    PortfolioPosition,
    SourceArtifact,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def sync_portfolio_fees(
    session: Session,
    provider: FundFeeProvider,
    raw_root: Path,
) -> IngestionRun:
    run = start_run(
        session,
        "sync_portfolio_fees",
        {"provider": provider.name, "provider_version": provider.version},
    )
    session.commit()
    shares = list(
        session.scalars(
            select(FundShare)
            .join(PortfolioPosition, PortfolioPosition.fund_share_id == FundShare.id)
            .where(PortfolioPosition.is_active.is_(True))
            .distinct()
            .order_by(FundShare.share_code)
        ).all()
    )
    written = failed = 0
    for share in shares:
        try:
            observation = provider.fetch(share.share_code)
            written += _store_observation(session, run, raw_root, share, observation)
            resolve_issues(
                session,
                issue_codes=("FUND_FEE_SYNC_FAILED",),
                fund_contract_id=share.fund_contract_id,
                fund_share_id=share.id,
            )
            session.commit()
        except Exception as error:
            session.rollback()
            failed += 1
            record_issue(
                session,
                ingestion_run_id=run.id,
                fund_contract_id=share.fund_contract_id,
                fund_share_id=share.id,
                issue_code="FUND_FEE_SYNC_FAILED",
                severity="ERROR",
                message=f"Fund-fee sync failed for {share.share_code}",
                details={"exception_type": type(error).__name__, "message": str(error)},
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


def _store_observation(
    session: Session,
    run: IngestionRun,
    raw_root: Path,
    share: FundShare,
    observation: FundFeeObservation,
) -> int:
    if observation.share_code != share.share_code:
        raise ValueError("Fee observation share code does not match requested share")
    suffix = ".html" if observation.mime_type == "text/html" else ".bin"
    archived = archive_bytes(
        raw_root,
        Path("fees") / observation.provider_name.lower() / share.share_code,
        "snapshot",
        suffix,
        observation.raw_payload,
    )
    artifact = session.scalar(
        select(SourceArtifact).where(
            SourceArtifact.source_provider == observation.provider_name,
            SourceArtifact.sha256 == archived.sha256,
        )
    )
    if artifact is None:
        artifact = SourceArtifact(
            ingestion_run_id=run.id,
            fund_contract_id=share.fund_contract_id,
            fund_share_id=share.id,
            artifact_type="FUND_FEE_HTML",
            source_provider=observation.provider_name,
            source_url=observation.source_url,
            local_path=str(archived.path.relative_to(raw_root.resolve())),
            mime_type=observation.mime_type,
            sha256=archived.sha256,
            byte_size=archived.byte_size,
            fetched_at=archived.fetched_at,
            metadata_json={
                "provider_version": observation.provider_version,
                "observed_at": observation.observed_at.isoformat(),
                "share_code": share.share_code,
            },
        )
        session.add(artifact)
        session.flush()
    snapshot_date = observation.observed_at.astimezone(SHANGHAI).date()
    row = session.scalar(
        select(DailyFundFee).where(
            DailyFundFee.fund_share_id == share.id,
            DailyFundFee.snapshot_date == snapshot_date,
            DailyFundFee.source_provider == observation.provider_name,
        )
    )
    created = row is None
    if row is None:
        row = DailyFundFee(
            fund_share_id=share.id,
            snapshot_date=snapshot_date,
            source_provider=observation.provider_name,
            source_url=observation.source_url,
            source_artifact_id=artifact.id,
            raw_payload_hash=archived.sha256,
        )
        session.add(row)
    row.management_fee_pct_annual = observation.management_fee_pct_annual
    row.custody_fee_pct_annual = observation.custody_fee_pct_annual
    row.sales_service_fee_pct_annual = observation.sales_service_fee_pct_annual
    row.standard_purchase_fee_pct = observation.standard_purchase_fee_pct
    row.discounted_purchase_fee_pct = observation.discounted_purchase_fee_pct
    row.source_url = observation.source_url
    row.source_artifact_id = artifact.id
    row.raw_payload_hash = archived.sha256
    row.confidence = observation.confidence
    return int(created)
