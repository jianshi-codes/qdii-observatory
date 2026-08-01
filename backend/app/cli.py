"""Command-line entry points for deterministic local ingestion workflows."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from backend.app.models import IngestionRun

CommandHandler = Callable[[argparse.Namespace], int]
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qdii", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Initialize local config without overwriting files.")
    init.set_defaults(handler=_init)

    doctor = subparsers.add_parser(
        "doctor",
        help="Check local configuration, storage, database, providers, and data freshness.",
    )
    doctor.add_argument(
        "--no-network", action="store_true", help="Skip provider DNS reachability checks."
    )
    doctor.set_defaults(handler=_doctor)

    preflight = subparsers.add_parser(
        "storage-preflight", help="Validate configured PostgreSQL and raw-data paths."
    )
    preflight.add_argument("--min-free-bytes", type=_nonnegative_int)
    preflight.set_defaults(handler=_storage_preflight)

    validate_universe = subparsers.add_parser(
        "validate-universe", help="Validate a CSV, XLSX, or JSON QDII universe without writing it."
    )
    validate_universe.add_argument("--file", type=Path, required=True)
    validate_universe.set_defaults(handler=_validate_universe)

    demo = subparsers.add_parser("load-demo", help="Load the offline synthetic demo dataset.")
    demo.add_argument(
        "--file", type=Path, default=REPOSITORY_ROOT / "examples/synthetic-demo/demo.json"
    )
    demo.set_defaults(handler=_load_demo)

    universe = subparsers.add_parser(
        "import-universe", help="Validate and idempotently import a CSV, XLSX, or JSON universe."
    )
    universe.add_argument("--file", "--xlsx", dest="file", type=Path, required=True)
    universe.set_defaults(handler=_import_universe)

    if _portfolio_enabled():
        portfolio = subparsers.add_parser(
            "import-portfolio", help="Import the enabled local-only Portfolio JSON snapshot."
        )
        portfolio.add_argument(
            "--json", type=Path, default=REPOSITORY_ROOT / ".data/private/portfolio.json"
        )
        portfolio.set_defaults(handler=_import_portfolio)

    report_sync = subparsers.add_parser(
        "sync-reports", help="Discover and archive official quarterly reports."
    )
    _add_quarter_arguments(report_sync)
    _add_fund_code_argument(report_sync)
    report_sync.set_defaults(handler=_sync_reports)

    report_parse = subparsers.add_parser(
        "parse-reports", help="Parse archived reports and calculate look-through exposure."
    )
    _add_quarter_arguments(report_parse)
    _add_fund_code_argument(report_parse)
    report_parse.set_defaults(handler=_parse_reports)

    nav_backfill = subparsers.add_parser(
        "backfill-nav", help="Idempotently backfill NAV history from the configured boundary."
    )
    _add_fund_code_argument(nav_backfill)
    nav_backfill.add_argument("--page-size", type=_page_size, default=20)
    nav_backfill.add_argument("--start-date", type=_date)
    nav_backfill.add_argument("--end-date", type=_date)
    nav_backfill.set_defaults(handler=_backfill_nav)

    sales_limits = subparsers.add_parser(
        "sync-sales-limits",
        help="Capture today's direct and distributor purchase-limit snapshots.",
    )
    _add_fund_code_argument(sales_limits)
    sales_limits.set_defaults(handler=_sync_sales_limits)

    if _portfolio_enabled():
        portfolio_fees = subparsers.add_parser(
            "sync-portfolio-fees",
            help="Capture fee schedules for shares in the enabled local Portfolio.",
        )
        portfolio_fees.set_defaults(handler=_sync_portfolio_fees)

    exchange_rates = subparsers.add_parser(
        "sync-exchange-rates",
        help="Capture the latest USD/CNY reference exchange rate.",
    )
    exchange_rates.set_defaults(handler=_sync_exchange_rates)

    daily = subparsers.add_parser(
        "sync-daily",
        help="Refresh NAV, prices, limits, portfolio fees, and USD/CNY reference rates.",
    )
    daily.add_argument("--lookback-days", type=_positive_int, default=10)
    daily.set_defaults(handler=_sync_daily)

    coverage = subparsers.add_parser(
        "coverage", help="Write deterministic quarterly CSV and Markdown coverage files."
    )
    _add_quarter_arguments(coverage)
    coverage.add_argument(
        "--output-dir",
        type=Path,
        default=REPOSITORY_ROOT / "reports" / "qdii",
    )
    coverage.set_defaults(handler=_coverage)

    analyze = subparsers.add_parser(
        "analyze-fund", help="Run DISCLOSED_HOLDINGS_BASELINE for one explicitly selected fund."
    )
    analyze.add_argument("--fund-code", type=_fund_code, required=True)
    analyze_period = analyze.add_mutually_exclusive_group(required=True)
    analyze_period.add_argument("--latest-report", action="store_true")
    analyze_period.add_argument("--year", type=_positive_int)
    analyze.add_argument("--quarter", type=_quarter)
    analyze.add_argument(
        "--proxy-config",
        type=Path,
        default=REPOSITORY_ROOT / "config/fund-analysis-proxies.local.yaml",
    )
    analyze.add_argument(
        "--export-mode", choices=("PUBLIC", "REDACTED", "PRIVATE"), default="REDACTED"
    )
    analyze.add_argument("--output-dir", type=Path, default=REPOSITORY_ROOT / ".data/analysis")
    analyze.set_defaults(handler=_analyze_fund)

    backup = subparsers.add_parser("backup", help="Create a local database backup.")
    backup.add_argument("--output-dir", type=Path, default=REPOSITORY_ROOT / ".data/backups")
    backup.set_defaults(handler=_backup)

    restore = subparsers.add_parser("restore", help="Restore a local database backup.")
    restore.add_argument("--file", type=Path, required=True)
    restore.add_argument("--confirm", action="store_true")
    restore.set_defaults(handler=_restore)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(REPOSITORY_ROOT / ".env", override=False)
    args = build_parser().parse_args(argv)
    handler: CommandHandler = args.handler
    try:
        return handler(args)
    except Exception as error:
        payload: dict[str, Any] = {
            "status": "error",
            "error_type": type(error).__name__,
            "message": str(error),
        }
        diagnostics = getattr(error, "diagnostics", None)
        if isinstance(diagnostics, dict):
            payload["diagnostics"] = diagnostics
        _print_json(payload, file=sys.stderr)
        return 1


def _portfolio_enabled() -> bool:
    from backend.app.config import get_settings

    return get_settings().portfolio_enabled


def _init(args: argparse.Namespace) -> int:
    from backend.app.operations import init_payload, initialize_project

    _print_json({"status": "ok", **init_payload(initialize_project(REPOSITORY_ROOT))})
    return 0


def _doctor(args: argparse.Namespace) -> int:
    from backend.app.config import get_settings
    from backend.app.operations import doctor

    checks = doctor(get_settings(), check_network=not args.no_network)
    failing = any(str(value).startswith("ERROR") for value in checks.values())
    _print_json({"status": "error" if failing else "ok", "checks": checks})
    return 1 if failing else 0


def _validate_universe(args: argparse.Namespace) -> int:
    from backend.app.ingestion.universe import load_universe

    universe = load_universe(args.file.resolve())
    _print_json(
        {
            "status": "valid",
            "contracts": len(universe.contracts),
            "shares": universe.share_count,
            "format": args.file.suffix.lower().lstrip("."),
        }
    )
    return 0


def _load_demo(args: argparse.Namespace) -> int:
    from backend.app.database import SessionLocal
    from backend.app.demo import load_synthetic_demo

    with SessionLocal() as session:
        result = load_synthetic_demo(session, args.file.resolve())
    _print_json({"status": "succeeded", **result})
    return 0


def _provider_client(*names: str) -> Any:
    from backend.app.ingestion.http import ProviderHttpClient, RetryPolicy
    from backend.app.ingestion.provider_registry import load_provider_registry

    registry = load_provider_registry()
    selected = [registry[name] for name in names if name in registry]
    disabled = [config.name for config in selected if not config.enabled]
    if disabled:
        raise ValueError(f"providers are disabled: {disabled}")
    if not selected:
        return ProviderHttpClient()
    return ProviderHttpClient(
        timeout_seconds=max(config.timeout_seconds for config in selected),
        min_interval_seconds=max(1 / config.rate_limit_per_second for config in selected),
        retry=RetryPolicy(attempts=max(config.retry_attempts for config in selected)),
        user_agent=selected[0].user_agent,
    )


def _storage_preflight(args: argparse.Namespace) -> int:
    from backend.app.ingestion.storage import storage_preflight

    targets = storage_preflight(min_free_bytes=args.min_free_bytes)
    _print_json(
        {
            "status": "ok",
            "targets": [
                {
                    "name": target.name,
                    "path": str(target.path),
                    "explicitly_configured": target.explicitly_configured,
                    "external": target.external,
                    "free_bytes": target.free_bytes,
                }
                for target in targets
            ],
        }
    )
    return 0


def _import_universe(args: argparse.Namespace) -> int:
    from backend.app.database import SessionLocal
    from backend.app.ingestion.runs import finish_run, record_issue, start_run
    from backend.app.ingestion.universe import (
        UniverseValidationError,
        import_universe,
        load_universe,
    )
    from backend.app.models import IngestionRun

    workbook = args.file.resolve()
    with SessionLocal() as session:
        run = start_run(session, "import_universe", {"source_file": workbook.name})
        session.commit()
        run_id = run.id
        try:
            universe = load_universe(workbook)
            contracts_written, shares_written = import_universe(session, universe, run)
            finish_run(
                run,
                status="succeeded",
                seen=len(universe.contracts),
                written=contracts_written + shares_written,
                failed=0,
            )
            session.commit()
        except Exception as error:
            session.rollback()
            failed_run = session.get(IngestionRun, run_id)
            if failed_run is None:
                raise
            diagnostics = (
                error.diagnostics
                if isinstance(error, UniverseValidationError)
                else {"exception_type": type(error).__name__}
            )
            record_issue(
                session,
                ingestion_run_id=failed_run.id,
                issue_code="UNIVERSE_IMPORT_FAILED",
                severity="ERROR",
                message=f"Universe import failed: {error}",
                details=diagnostics,
            )
            finish_run(
                failed_run,
                status="failed",
                seen=int(diagnostics.get("actual_contract_count", 0)),
                written=0,
                failed=1,
                error=str(error),
            )
            session.commit()
            raise
    _print_json(
        {
            "status": "succeeded",
            "run_id": run_id,
            "contracts_written": contracts_written,
            "shares_written": shares_written,
        }
    )
    return 0


def _import_portfolio(args: argparse.Namespace) -> int:
    from backend.app.database import SessionLocal
    from backend.app.portfolio import import_portfolio

    path = args.json.resolve()
    with SessionLocal() as session:
        result = import_portfolio(session, path)
    _print_json(
        {
            "status": "succeeded",
            "portfolio_path": str(path),
            "positions_seen": result.positions_seen,
            "positions_written": result.positions_written,
            "cash_flows_written": result.cash_flows_written,
        }
    )
    return 0


def _sync_reports(args: argparse.Namespace) -> int:
    from backend.app.database import SessionLocal
    from backend.app.ingestion.providers.reports import CsrcReportProvider
    from backend.app.ingestion.report_pipeline import sync_reports
    from backend.app.ingestion.storage import raw_data_dir

    year, quarter = _resolve_period(args)
    raw_root = raw_data_dir()
    with SessionLocal() as session, _provider_client("csrc_reports") as http:
        run = sync_reports(
            session,
            CsrcReportProvider(http),
            raw_root,
            year=year,
            quarter=quarter,
            representative_codes=_code_set(args.fund_codes),
        )
    return _report_run(run)


def _parse_reports(args: argparse.Namespace) -> int:
    from backend.app.database import SessionLocal
    from backend.app.ingestion.lookthrough import calculate_and_store_lookthrough
    from backend.app.ingestion.report_pipeline import parse_reports
    from backend.app.ingestion.storage import raw_data_dir

    year, quarter = _resolve_period(args)
    raw_root = raw_data_dir()
    with SessionLocal() as session:
        run = parse_reports(
            session,
            raw_root,
            year=year,
            quarter=quarter,
            representative_codes=_code_set(args.fund_codes),
        )
        lookthrough = calculate_and_store_lookthrough(session, year=year, quarter=quarter)
        session.commit()
    return _report_run(run, lookthrough_reports=len(lookthrough))


def _backfill_nav(args: argparse.Namespace) -> int:
    from backend.app.database import SessionLocal
    from backend.app.ingestion.nav_pipeline import sync_nav
    from backend.app.ingestion.providers.nav import EastmoneyNavProvider
    from backend.app.ingestion.storage import raw_data_dir

    raw_root = raw_data_dir()
    with SessionLocal() as session, _provider_client("eastmoney_nav") as http:
        share_codes = _share_codes_for_funds(session, _code_set(args.fund_codes))
        run = sync_nav(
            session,
            EastmoneyNavProvider(http),
            raw_root,
            start_date=args.start_date,
            end_date=args.end_date,
            share_codes=share_codes,
            page_size=args.page_size,
        )
    return _report_run(run)


def _sync_daily(args: argparse.Namespace) -> int:
    from backend.app.database import SessionLocal
    from backend.app.ingestion.fee_pipeline import sync_portfolio_fees
    from backend.app.ingestion.fx_pipeline import sync_exchange_rates
    from backend.app.ingestion.limit_pipeline import sync_purchase_limits
    from backend.app.ingestion.nav_pipeline import sync_daily
    from backend.app.ingestion.providers.fees import EastmoneyFundFeeProvider
    from backend.app.ingestion.providers.fx import EcbExchangeRateProvider
    from backend.app.ingestion.providers.limits import (
        CsrcPurchaseLimitProvider,
        EastmoneyPurchaseLimitProvider,
    )
    from backend.app.ingestion.providers.market import EastmoneyMarketPriceProvider
    from backend.app.ingestion.providers.nav import EastmoneyNavProvider
    from backend.app.ingestion.storage import raw_data_dir

    raw_root = raw_data_dir()
    with (
        SessionLocal() as session,
        _provider_client("eastmoney_nav", "eastmoney_market", "csrc_reports", "ecb_fx") as http,
    ):
        nav_run, market_run = sync_daily(
            session,
            EastmoneyNavProvider(http),
            EastmoneyMarketPriceProvider(http),
            raw_root,
            lookback_days=args.lookback_days,
        )
        limit_run = sync_purchase_limits(
            session,
            CsrcPurchaseLimitProvider(http),
            EastmoneyPurchaseLimitProvider(http),
            raw_root,
        )
        fx_run = sync_exchange_rates(session, EcbExchangeRateProvider(http), raw_root)
        runs = [nav_run, market_run, limit_run, fx_run]
        if _portfolio_enabled():
            runs.append(sync_portfolio_fees(session, EastmoneyFundFeeProvider(http), raw_root))
    _print_json(
        {
            "status": (
                "succeeded" if all(run.status == "succeeded" for run in runs) else "partial"
            ),
            "runs": [_run_payload(run) for run in runs],
        }
    )
    return 0 if all(run.status == "succeeded" for run in runs) else 2


def _sync_sales_limits(args: argparse.Namespace) -> int:
    from backend.app.database import SessionLocal
    from backend.app.ingestion.limit_pipeline import sync_purchase_limits
    from backend.app.ingestion.providers.limits import (
        CsrcPurchaseLimitProvider,
        EastmoneyPurchaseLimitProvider,
    )
    from backend.app.ingestion.storage import raw_data_dir

    raw_root = raw_data_dir()
    with SessionLocal() as session, _provider_client("csrc_reports") as http:
        run = sync_purchase_limits(
            session,
            CsrcPurchaseLimitProvider(http),
            EastmoneyPurchaseLimitProvider(http),
            raw_root,
            fund_codes=_code_set(args.fund_codes),
        )
    return _report_run(run)


def _sync_portfolio_fees(args: argparse.Namespace) -> int:
    from backend.app.database import SessionLocal
    from backend.app.ingestion.fee_pipeline import sync_portfolio_fees
    from backend.app.ingestion.providers.fees import EastmoneyFundFeeProvider
    from backend.app.ingestion.storage import raw_data_dir

    raw_root = raw_data_dir()
    with SessionLocal() as session, _provider_client("eastmoney_nav") as http:
        run = sync_portfolio_fees(session, EastmoneyFundFeeProvider(http), raw_root)
    return _report_run(run)


def _sync_exchange_rates(args: argparse.Namespace) -> int:
    from backend.app.database import SessionLocal
    from backend.app.ingestion.fx_pipeline import sync_exchange_rates
    from backend.app.ingestion.providers.fx import EcbExchangeRateProvider
    from backend.app.ingestion.storage import raw_data_dir

    raw_root = raw_data_dir()
    with SessionLocal() as session, _provider_client("ecb_fx") as http:
        run = sync_exchange_rates(session, EcbExchangeRateProvider(http), raw_root)
    return _report_run(run)


def _coverage(args: argparse.Namespace) -> int:
    from backend.app.coverage import generate_coverage
    from backend.app.database import SessionLocal

    year, quarter = _resolve_period(args)
    output_dir = args.output_dir.resolve()
    with SessionLocal() as session:
        result = generate_coverage(
            session,
            output_dir,
            year=year,
            quarter=quarter,
        )
    _print_json(
        {
            "status": "succeeded",
            "fund_count": len(result.rows),
            "csv_path": str(result.csv_path),
            "markdown_path": str(result.markdown_path),
        }
    )
    return 0


def _analyze_fund(args: argparse.Namespace) -> int:
    from backend.app.analysis import analyze_disclosed_holdings, export_evidence
    from backend.app.database import SessionLocal

    if args.year is not None and args.quarter is None:
        raise ValueError("--year requires --quarter")
    with SessionLocal() as session:
        result = analyze_disclosed_holdings(
            session,
            fund_code=args.fund_code,
            proxy_config=args.proxy_config.resolve(),
            year=args.year,
            quarter=args.quarter,
            latest_report=args.latest_report,
        )
    evidence_path = export_evidence(result, args.output_dir.resolve(), args.export_mode)
    _print_json(
        {"status": "succeeded", "result": asdict(result), "evidence_path": str(evidence_path)}
    )
    return 0


def _backup(args: argparse.Namespace) -> int:
    from backend.app.config import get_settings
    from backend.app.operations import backup_database

    path = backup_database(get_settings(), args.output_dir.resolve())
    _print_json({"status": "succeeded", "backup_path": str(path)})
    return 0


def _restore(args: argparse.Namespace) -> int:
    from backend.app.config import get_settings
    from backend.app.operations import restore_database

    restore_database(get_settings(), args.file.resolve(), confirmed=args.confirm)
    _print_json({"status": "succeeded", "restored_from": str(args.file.resolve())})
    return 0


def _report_run(run: IngestionRun, **extra: object) -> int:
    _print_json({**_run_payload(run), **extra})
    return 0 if run.status == "succeeded" else 2


def _run_payload(run: IngestionRun) -> dict[str, object]:
    return {
        "run_id": run.id,
        "job_type": run.job_type,
        "status": run.status,
        "records_seen": run.records_seen,
        "records_written": run.records_written,
        "records_failed": run.records_failed,
        "error_message": run.error_message,
    }


def _print_json(payload: dict[str, Any], *, file: Any | None = None) -> None:
    output = file if file is not None else sys.stdout
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
        file=output,
    )


def _add_quarter_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--year", type=_positive_int)
    parser.add_argument("--quarter", type=_quarter)
    parser.add_argument("--latest-quarter", action="store_true")


def _resolve_period(args: argparse.Namespace, *, today: date | None = None) -> tuple[int, int]:
    if args.latest_quarter:
        if args.year is not None or args.quarter is not None:
            raise ValueError("--latest-quarter cannot be combined with --year or --quarter")
        return _latest_completed_quarter(today or date.today())
    if args.year is None or args.quarter is None:
        raise ValueError("provide both --year and --quarter, or --latest-quarter")
    return args.year, args.quarter


def _latest_completed_quarter(today: date) -> tuple[int, int]:
    current_quarter = (today.month - 1) // 3 + 1
    if current_quarter == 1:
        return today.year - 1, 4
    return today.year, current_quarter - 1


def _add_fund_code_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--fund-code",
        dest="fund_codes",
        action="append",
        type=_fund_code,
        help="Limit the task to one code; repeat for multiple codes.",
    )


def _code_set(values: list[str] | None) -> set[str] | None:
    return set(values) if values else None


def _share_codes_for_funds(
    session: Session, representative_codes: set[str] | None
) -> set[str] | None:
    if representative_codes is None:
        return None
    from sqlalchemy import select

    from backend.app.models import FundContract, FundShare

    rows = session.execute(
        select(FundContract.representative_code, FundShare.share_code)
        .join(FundShare, FundShare.fund_contract_id == FundContract.id)
        .where(FundContract.representative_code.in_(representative_codes))
    )
    codes_by_contract: dict[str, set[str]] = {}
    for representative_code, share_code in rows:
        codes_by_contract.setdefault(representative_code, set()).add(share_code)
    missing = representative_codes - codes_by_contract.keys()
    if missing:
        raise ValueError(f"Fund contracts not found or have no shares: {sorted(missing)}")
    return set().union(*codes_by_contract.values())


def _fund_code(value: str) -> str:
    if len(value) != 6 or not value.isdigit():
        raise argparse.ArgumentTypeError("fund code must contain exactly six digits")
    return value


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be nonnegative")
    return parsed


def _page_size(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > 20:
        raise argparse.ArgumentTypeError("page size must not exceed the provider limit of 20")
    return parsed


def _quarter(value: str) -> int:
    parsed = int(value)
    if parsed not in {1, 2, 3, 4}:
        raise argparse.ArgumentTypeError("quarter must be in 1..4")
    return parsed


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error


if __name__ == "__main__":
    raise SystemExit(main())
