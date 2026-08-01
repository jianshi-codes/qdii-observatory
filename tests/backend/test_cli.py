from __future__ import annotations

import json
import os
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from backend.app import cli, database
from backend.app.config import get_settings
from backend.app.ingestion import report_pipeline, storage
from backend.app.ingestion.providers import reports as report_providers
from backend.app.models import FundContract, FundShare


@pytest.mark.parametrize(
    ("argv", "command"),
    [
        (["storage-preflight"], "storage-preflight"),
        (["init"], "init"),
        (["doctor", "--no-network"], "doctor"),
        (["validate-universe", "--file", "universe.csv"], "validate-universe"),
        (["import-universe", "--file", "universe.xlsx"], "import-universe"),
        (["sync-reports", "--year", "2026", "--quarter", "2"], "sync-reports"),
        (["sync-reports", "--latest-quarter"], "sync-reports"),
        (["parse-reports", "--year", "2026", "--quarter", "2"], "parse-reports"),
        (["backfill-nav"], "backfill-nav"),
        (["sync-sales-limits", "--fund-code", "000834"], "sync-sales-limits"),
        (["sync-exchange-rates"], "sync-exchange-rates"),
        (["sync-daily", "--lookback-days", "10"], "sync-daily"),
        (["coverage", "--year", "2026", "--quarter", "2"], "coverage"),
        (["analyze-fund", "--fund-code", "123456", "--latest-report"], "analyze-fund"),
        (["backup"], "backup"),
        (["restore", "--file", "backup.dump", "--confirm"], "restore"),
    ],
)
def test_parser_exposes_every_documented_command(argv: list[str], command: str) -> None:
    assert cli.build_parser().parse_args(argv).command == command


def test_parser_rejects_invalid_quarter_and_fund_code() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["sync-reports", "--quarter", "5"])
    with pytest.raises(SystemExit):
        parser.parse_args(["backfill-nav", "--fund-code", "834"])


def test_nav_backfill_has_no_project_specific_date_boundary() -> None:
    args = cli.build_parser().parse_args(["backfill-nav"])

    assert args.start_date is None
    assert args.end_date is None
    assert args.page_size == 20


def test_storage_preflight_command_emits_machine_readable_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("QDII_CLI_DOTENV_PROBE=loaded\n", encoding="utf-8")
    monkeypatch.setattr(cli, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.delenv("QDII_CLI_DOTENV_PROBE", raising=False)
    target = SimpleNamespace(
        name="QDII_RAW_DATA_DIR",
        path=tmp_path,
        explicitly_configured=True,
        external=False,
        free_bytes=123456,
    )

    def fake_preflight(min_free_bytes: int | None) -> tuple[SimpleNamespace, ...]:
        assert os.getenv("QDII_CLI_DOTENV_PROBE") == "loaded"
        assert min_free_bytes == 0
        return (target,)

    monkeypatch.setattr(storage, "storage_preflight", fake_preflight)

    assert cli.main(["storage-preflight", "--min-free-bytes", "0"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["targets"][0]["path"] == str(tmp_path)


def test_sync_reports_command_wires_provider_pipeline_and_single_fund_filter(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db_session: Session,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeHttp:
        def __enter__(self) -> FakeHttp:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def fake_sync_reports(
        session: Session,
        provider: object,
        raw_root: Path,
        **kwargs: object,
    ) -> SimpleNamespace:
        captured.update(
            session=session,
            provider=provider,
            raw_root=raw_root,
            kwargs=kwargs,
        )
        return SimpleNamespace(
            id=7,
            job_type="sync_reports",
            status="succeeded",
            records_seen=1,
            records_written=1,
            records_failed=0,
            error_message=None,
        )

    monkeypatch.setattr(database, "SessionLocal", lambda: nullcontext(db_session))
    monkeypatch.setattr(cli, "_provider_client", lambda *_: FakeHttp())
    monkeypatch.setattr(report_providers, "CsrcReportProvider", lambda client: ("provider", client))
    monkeypatch.setattr(storage, "raw_data_dir", lambda: tmp_path)
    monkeypatch.setattr(report_pipeline, "sync_reports", fake_sync_reports)

    exit_code = cli.main(
        [
            "sync-reports",
            "--year",
            "2026",
            "--quarter",
            "2",
            "--fund-code",
            "000834",
        ]
    )
    assert exit_code == 0
    assert captured["session"] is db_session
    assert captured["raw_root"] == tmp_path
    assert captured["kwargs"] == {
        "year": 2026,
        "quarter": 2,
        "representative_codes": {"000834"},
    }
    assert json.loads(capsys.readouterr().out)["run_id"] == 7


def test_python_database_url_is_explicit_and_does_not_derive_from_pg_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QDII_PG_PORT", "6543")
    monkeypatch.setenv(
        "QDII_DATABASE_URL",
        "postgresql+psycopg://qdii:qdii@localhost:7777/qdii_observatory",
    )
    get_settings.cache_clear()
    assert get_settings().database_url.endswith("localhost:7777/qdii_observatory")
    get_settings.cache_clear()


def test_nav_single_fund_filter_expands_to_every_contract_share(
    db_session: Session,
) -> None:
    fund = FundContract(
        canonical_name="多份额基金",
        manager_name="管理人",
        representative_code="000834",
    )
    db_session.add(fund)
    db_session.flush()
    db_session.add_all(
        [
            FundShare(
                fund_contract_id=fund.id,
                share_code="000834",
                currency="CNY",
            ),
            FundShare(
                fund_contract_id=fund.id,
                share_code="008971",
                currency="CNY",
            ),
        ]
    )
    db_session.commit()
    assert cli._share_codes_for_funds(db_session, {"000834"}) == {
        "000834",
        "008971",
    }
