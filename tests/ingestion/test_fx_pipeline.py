from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ingestion.fx_pipeline import sync_exchange_rates
from backend.app.ingestion.providers.base import ExchangeRateObservation, ProviderSchemaError
from backend.app.ingestion.providers.fx import parse_ecb_reference_rates
from backend.app.models import DailyExchangeRate

ECB_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<Envelope><Cube><Cube time="2026-07-31">
  <Cube currency="USD" rate="1.20"/>
  <Cube currency="CNY" rate="7.20"/>
</Cube></Cube></Envelope>
"""


def test_parse_ecb_reference_rates_calculates_usd_cny_cross_rate() -> None:
    observation = parse_ecb_reference_rates(
        ECB_XML,
        source_url="https://example.test/eurofxref-daily.xml",
    )

    assert observation.rate_date == date(2026, 7, 31)
    assert observation.base_currency == "USD"
    assert observation.quote_currency == "CNY"
    assert observation.rate == Decimal("6.000000000000")


def test_parse_ecb_reference_rates_fails_closed_without_required_currency() -> None:
    with pytest.raises(ProviderSchemaError, match="USD or CNY"):
        parse_ecb_reference_rates(
            ECB_XML.replace(b'currency="CNY"', b'currency="GBP"'),
            source_url="https://example.test/eurofxref-daily.xml",
        )


def test_sync_exchange_rates_archives_and_writes_snapshot(db_session: Session, tmp_path) -> None:
    class FakeProvider:
        name = "ECB_FIXTURE"
        version = "v1"

        def fetch(self) -> ExchangeRateObservation:
            return ExchangeRateObservation(
                provider_name=self.name,
                provider_version=self.version,
                base_currency="USD",
                quote_currency="CNY",
                rate_date=date(2026, 7, 31),
                rate=Decimal("6.75"),
                observed_at=datetime(2026, 8, 1, tzinfo=UTC),
                raw_payload=ECB_XML,
                source_url="https://example.test/eurofxref-daily.xml",
                mime_type="application/xml",
                confidence=Decimal("0.99"),
            )

    run = sync_exchange_rates(db_session, FakeProvider(), tmp_path)

    assert run.status == "succeeded"
    row = db_session.scalar(select(DailyExchangeRate))
    assert row is not None
    assert row.rate == Decimal("6.750000000000")
    assert (tmp_path / "fx" / "ecb_fixture").is_dir()
