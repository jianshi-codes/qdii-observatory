from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.ingestion.ooxml import list_sheets, read_sheet
from backend.app.ingestion.runs import start_run
from backend.app.ingestion.universe import (
    FIELD_ALIASES,
    UniverseValidationError,
    import_universe,
    load_universe,
    split_share_codes,
)
from backend.app.models import FundContract, FundShare


def test_share_code_splitter_preserves_leading_zeroes_and_delimiters() -> None:
    assert split_share_codes("123456、234567，345678; 456789") == (
        "123456",
        "234567",
        "345678",
        "456789",
    )


def test_sample_universe_is_small_synthetic_and_generic(universe_path: Path) -> None:
    universe = load_universe(universe_path)

    assert len(universe.contracts) == 3
    assert universe.share_count == 5
    assert {item.wrapper_type for item in universe.contracts} == {
        "DIRECT",
        "ETF",
        "ETF_FEEDER",
    }
    assert all(
        item.representative_code in {share.code for share in item.shares}
        for item in universe.contracts
    )


def test_downloadable_xlsx_template_matches_import_schema() -> None:
    template = (
        Path(__file__).resolve().parents[2]
        / "frontend"
        / "public"
        / "templates"
        / "universe-import-template.xlsx"
    )

    assert list_sheets(template) == ["基金合同明细", "填写说明"]
    assert read_sheet(template, "基金合同明细") == [list(FIELD_ALIASES)]


def test_json_universe_supports_one_contract(tmp_path: Path) -> None:
    path = tmp_path / "universe.json"
    path.write_text(
        json.dumps(
            {
                "funds": [
                    {
                        "representative_code": "654321",
                        "representative_name": "Synthetic Fund",
                        "manager_name": "Example Manager",
                        "canonical_name": "Synthetic Contract",
                        "share_codes": ["654321"],
                        "share_currencies": ["CNY"],
                        "region": "Global",
                        "category": "Broad",
                        "strategy_type": "Active",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    universe = load_universe(path)

    assert len(universe.contracts) == 1
    assert universe.contracts[0].enabled is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("representative_code", "123", "six digits"),
        ("share_currencies", "XYZ", "unsupported currencies"),
        ("wrapper_type", "UNKNOWN_WRAPPER", "unsupported wrapper_type"),
    ],
)
def test_validation_reports_invalid_fields(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    source = {
        "representative_code": "123456",
        "representative_name": "Synthetic Fund",
        "manager_name": "Example Manager",
        "canonical_name": "Synthetic Contract",
        "share_codes": "123456",
        "share_currencies": "CNY",
        "region": "Global",
        "category": "Broad",
        "strategy_type": "Active",
        "wrapper_type": "DIRECT",
    }
    source[field] = value
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps([source]), encoding="utf-8")

    with pytest.raises(UniverseValidationError) as caught:
        load_universe(path)

    assert message in str(caught.value.diagnostics["row_errors"])


def test_universe_import_is_idempotent(
    db_session: Session,
    universe_path: Path,
) -> None:
    universe = load_universe(universe_path)
    run = start_run(db_session, "import_universe", {"source_file": universe_path.name})

    assert import_universe(db_session, universe, run) == (3, 5)
    db_session.commit()
    first_share_ids = dict(db_session.execute(select(FundShare.share_code, FundShare.id)).all())

    assert import_universe(db_session, universe, run) == (3, 5)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(FundContract)) == 3
    assert db_session.scalar(select(func.count()).select_from(FundShare)) == 5
    assert (
        dict(db_session.execute(select(FundShare.share_code, FundShare.id)).all())
        == first_share_ids
    )
