"""Archive and persist the latest USD/CNY reference rate."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ingestion.archive import archive_bytes
from backend.app.ingestion.providers.base import ExchangeRateObservation, ExchangeRateProvider
from backend.app.ingestion.runs import finish_run, record_issue, resolve_issues, start_run
from backend.app.models import DailyExchangeRate, IngestionRun, SourceArtifact


def sync_exchange_rates(
    session: Session,
    provider: ExchangeRateProvider,
    raw_root: Path,
) -> IngestionRun:
    run = start_run(
        session,
        "sync_exchange_rates",
        {"provider": provider.name, "provider_version": provider.version},
    )
    session.commit()
    try:
        observation = provider.fetch()
        written = _store_observation(session, run, raw_root, observation)
        resolve_issues(session, issue_codes=("EXCHANGE_RATE_SYNC_FAILED",))
        finish_run(run, status="succeeded", seen=1, written=written, failed=0)
    except Exception as error:
        session.rollback()
        record_issue(
            session,
            ingestion_run_id=run.id,
            issue_code="EXCHANGE_RATE_SYNC_FAILED",
            severity="ERROR",
            message="USD/CNY exchange-rate sync failed",
            details={"exception_type": type(error).__name__, "message": str(error)},
        )
        finish_run(run, status="failed", seen=1, written=0, failed=1, error=str(error))
    session.commit()
    return run


def _store_observation(
    session: Session,
    run: IngestionRun,
    raw_root: Path,
    observation: ExchangeRateObservation,
) -> int:
    if (observation.base_currency, observation.quote_currency) != ("USD", "CNY"):
        raise ValueError("Portfolio exchange-rate observation must be USD/CNY")
    suffix = ".xml" if "xml" in observation.mime_type else ".bin"
    archived = archive_bytes(
        raw_root,
        Path("fx") / observation.provider_name.lower(),
        observation.rate_date.isoformat(),
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
            artifact_type="FX_RATE_XML",
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
                "base_currency": observation.base_currency,
                "quote_currency": observation.quote_currency,
                "rate_date": observation.rate_date.isoformat(),
            },
        )
        session.add(artifact)
        session.flush()
    row = session.scalar(
        select(DailyExchangeRate).where(
            DailyExchangeRate.base_currency == observation.base_currency,
            DailyExchangeRate.quote_currency == observation.quote_currency,
            DailyExchangeRate.rate_date == observation.rate_date,
            DailyExchangeRate.source_provider == observation.provider_name,
        )
    )
    created = row is None
    if row is None:
        row = DailyExchangeRate(
            base_currency=observation.base_currency,
            quote_currency=observation.quote_currency,
            rate_date=observation.rate_date,
            source_provider=observation.provider_name,
            source_url=observation.source_url,
            source_artifact_id=artifact.id,
            raw_payload_hash=archived.sha256,
        )
        session.add(row)
    row.rate = observation.rate
    row.source_url = observation.source_url
    row.source_artifact_id = artifact.id
    row.raw_payload_hash = archived.sha256
    row.confidence = observation.confidence
    return int(created)
