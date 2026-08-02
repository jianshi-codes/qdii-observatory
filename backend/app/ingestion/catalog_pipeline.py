"""Import explicitly selected public QDII catalog records with source evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ingestion.archive import archive_bytes
from backend.app.ingestion.providers.base import (
    FundCatalogProvider,
    FundCatalogSnapshot,
    ProviderSchemaError,
)
from backend.app.ingestion.runs import finish_run, record_issue, start_run
from backend.app.ingestion.universe import (
    ContractInput,
    UniverseInput,
    _share_metadata,
    import_universe,
)
from backend.app.models import FundContract, FundShare, SourceArtifact


@dataclass(frozen=True, slots=True)
class PublicImportResult:
    status: Literal["succeeded", "partial", "failed"]
    imported_codes: tuple[str, ...]
    failures: dict[str, str]


def import_public_funds(
    session: Session,
    provider: FundCatalogProvider,
    raw_root: Path,
    fund_codes: tuple[str, ...],
) -> PublicImportResult:
    """Lookup and import only the explicitly selected codes; partial failures stay visible."""

    run = start_run(
        session,
        "import_public_funds",
        {"provider": provider.name, "version": provider.version, "fund_codes": list(fund_codes)},
    )
    session.commit()
    imported: list[str] = []
    failures: dict[str, str] = {}
    for code in fund_codes:
        try:
            snapshot = provider.lookup(code)
            candidate = snapshot.candidates[0]
            if not candidate.manager_name:
                raise ProviderSchemaError(
                    f"Exact public fund metadata is missing manager_name for {code}"
                )
            universe = UniverseInput(
                workbook=Path(f"public-catalog-{code}.json"),
                requested_sheet="PUBLIC_CATALOG",
                actual_sheet="PUBLIC_CATALOG",
                sheet_alias_used=False,
                contracts=(
                    ContractInput(
                        source_row=1,
                        representative_code=candidate.fund_code,
                        representative_fund_name=candidate.fund_name,
                        manager_name=candidate.manager_name,
                        canonical_name=candidate.fund_name,
                        declared_share_count=1,
                        shares=(
                            _share_metadata(
                                candidate.fund_code,
                                candidate.fund_name,
                                candidate.currency,
                                candidate.wrapper_type,
                            ),
                        ),
                        region="OVERSEAS_UNSPECIFIED",
                        original_category=candidate.category,
                        strategy_type=candidate.category,
                        wrapper_type=candidate.wrapper_type,
                        tech_scope=(
                            "GLOBAL_TECHNOLOGY_INTERNET"
                            if candidate.research_scope == "TECHNOLOGY"
                            else "UNKNOWN"
                        ),
                        enabled=True,
                    ),
                ),
            )
            with session.begin_nested():
                import_universe(session, universe, run)
                _archive_catalog_snapshot(
                    session,
                    run.id,
                    raw_root,
                    snapshot,
                    provider.name,
                    provider.version,
                )
            session.commit()
            imported.append(code)
        except Exception as error:
            session.rollback()
            failures[code] = str(error)
            record_issue(
                session,
                ingestion_run_id=run.id,
                issue_code="PUBLIC_FUND_IMPORT_FAILED",
                severity="ERROR",
                message=f"Public fund import failed for {code}: {error}",
                details={"provider": provider.name, "exception_type": type(error).__name__},
            )
            session.commit()
    status: Literal["succeeded", "partial", "failed"] = (
        "succeeded" if not failures else "failed" if not imported else "partial"
    )
    finish_run(
        run,
        status=status,
        seen=len(fund_codes),
        written=len(imported),
        failed=len(failures),
        error=None if not failures else f"{len(failures)} selected fund(s) failed",
    )
    session.commit()
    return PublicImportResult(status, tuple(imported), failures)


def _archive_catalog_snapshot(
    session: Session,
    run_id: int,
    raw_root: Path,
    snapshot: FundCatalogSnapshot,
    provider_name: str,
    provider_version: str,
) -> None:
    candidate = snapshot.candidates[0]
    suffix = ".json" if "json" in snapshot.mime_type else ".html"
    archived = archive_bytes(
        raw_root,
        Path("catalog") / "eastmoney" / candidate.fund_code,
        "fund-metadata",
        suffix,
        snapshot.raw_payload,
    )
    existing = session.scalar(
        select(SourceArtifact).where(
            SourceArtifact.source_provider == provider_name,
            SourceArtifact.sha256 == archived.sha256,
        )
    )
    if existing is not None:
        return
    contract = session.scalar(
        select(FundContract).where(
            FundContract.representative_code == candidate.fund_code
        )
    )
    share = session.scalar(select(FundShare).where(FundShare.share_code == candidate.fund_code))
    if contract is None or share is None:
        raise RuntimeError("catalog import did not create the selected fund")
    session.add(
        SourceArtifact(
            ingestion_run_id=run_id,
            fund_contract_id=contract.id,
            fund_share_id=share.id,
            artifact_type="FUND_CATALOG_JSON" if suffix == ".json" else "FUND_CATALOG_HTML",
            source_provider=provider_name,
            source_url=snapshot.source_url,
            local_path=str(archived.path.relative_to(raw_root.resolve())),
            mime_type=snapshot.mime_type,
            sha256=archived.sha256,
            byte_size=archived.byte_size,
            fetched_at=archived.fetched_at,
            metadata_json={
                "provider_version": provider_version,
                "fund_code": candidate.fund_code,
                "category": candidate.category,
                "research_scope": candidate.research_scope,
            },
        )
    )
