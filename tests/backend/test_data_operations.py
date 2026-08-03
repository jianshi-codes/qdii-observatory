from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from backend.app import data_operations
from backend.app.models import FundContract, FundShare


def test_daily_operation_limits_nav_and_sales_requests_to_selected_fund(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected = FundContract(
        canonical_name="目标基金",
        manager_name="目标管理人",
        representative_code="000001",
        is_user_selected=True,
    )
    other = FundContract(
        canonical_name="其他基金",
        manager_name="其他管理人",
        representative_code="000002",
        is_user_selected=True,
    )
    db_session.add_all([selected, other])
    db_session.flush()
    db_session.add_all(
        [
            FundShare(fund_contract_id=selected.id, share_code="000001", currency="CNY"),
            FundShare(fund_contract_id=selected.id, share_code="000003", currency="USD"),
            FundShare(fund_contract_id=other.id, share_code="000002", currency="CNY"),
        ]
    )
    db_session.commit()
    captured: dict[str, object] = {}
    run = SimpleNamespace(status="succeeded")

    monkeypatch.setattr(data_operations, "provider_client", lambda *_: nullcontext(object()))
    monkeypatch.setattr(data_operations, "EastmoneyNavProvider", lambda http: ("nav", http))
    monkeypatch.setattr(
        data_operations, "EastmoneyMarketPriceProvider", lambda http: ("market", http)
    )
    monkeypatch.setattr(
        data_operations, "CsrcPurchaseLimitProvider", lambda http: ("direct", http)
    )
    monkeypatch.setattr(
        data_operations, "EastmoneyPurchaseLimitProvider", lambda http: ("distribution", http)
    )
    monkeypatch.setattr(data_operations, "EcbExchangeRateProvider", lambda http: ("fx", http))

    def fake_daily(*args: object, **kwargs: object) -> tuple[object, object]:
        captured["daily_kwargs"] = kwargs
        return run, run

    def fake_limits(*args: object, **kwargs: object) -> object:
        captured["limit_kwargs"] = kwargs
        return run

    monkeypatch.setattr(data_operations, "sync_daily", fake_daily)
    monkeypatch.setattr(data_operations, "sync_purchase_limits", fake_limits)
    monkeypatch.setattr(data_operations, "sync_exchange_rates", lambda *args: run)

    codes = data_operations.selected_fund_codes(db_session, {"000001"})
    result = data_operations.sync_daily_data(
        db_session,
        tmp_path,
        fund_codes=codes,
        lookback_days=10,
    )

    assert result.status == "succeeded"
    assert captured["daily_kwargs"] == {
        "lookback_days": 10,
        "share_codes": {"000001", "000003"},
    }
    assert captured["limit_kwargs"] == {"fund_codes": {"000001"}}
