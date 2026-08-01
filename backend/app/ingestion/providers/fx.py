"""ECB reference-rate provider for the portfolio's USD/CNY conversion."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from xml.etree import ElementTree

from backend.app.ingestion.http import ProviderHttpClient
from backend.app.ingestion.providers.base import ExchangeRateObservation, ProviderSchemaError

RATE_SCALE = Decimal("0.000000000001")


class EcbExchangeRateProvider:
    name = "ECB_REFERENCE_RATE"
    version = "eurofxref-daily-xml-v1"
    endpoint = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

    def __init__(self, http: ProviderHttpClient) -> None:
        self.http = http

    def fetch(self) -> ExchangeRateObservation:
        response = self.http.request(
            "GET",
            self.endpoint,
            headers={"Accept": "application/xml,text/xml"},
        )
        return parse_ecb_reference_rates(
            response.content,
            source_url=str(response.url),
            mime_type=response.headers.get("content-type", "application/xml").split(";", 1)[0],
        )


def parse_ecb_reference_rates(
    payload: bytes,
    *,
    source_url: str,
    mime_type: str = "application/xml",
) -> ExchangeRateObservation:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise ProviderSchemaError("ECB reference-rate response is not valid XML") from error

    dated_nodes = [node for node in root.iter() if "time" in node.attrib]
    if len(dated_nodes) != 1:
        raise ProviderSchemaError("ECB daily response must contain exactly one dated rate set")
    dated_node = dated_nodes[0]
    try:
        rate_date = date.fromisoformat(dated_node.attrib["time"])
    except ValueError as error:
        raise ProviderSchemaError("ECB reference-rate date is invalid") from error

    rates = {
        node.attrib["currency"]: node.attrib["rate"]
        for node in dated_node
        if "currency" in node.attrib and "rate" in node.attrib
    }
    try:
        usd_per_eur = Decimal(rates["USD"])
        cny_per_eur = Decimal(rates["CNY"])
    except (KeyError, InvalidOperation) as error:
        raise ProviderSchemaError("ECB response is missing valid USD or CNY rates") from error
    if usd_per_eur <= 0 or cny_per_eur <= 0:
        raise ProviderSchemaError("ECB USD and CNY rates must be positive")

    return ExchangeRateObservation(
        provider_name=EcbExchangeRateProvider.name,
        provider_version=EcbExchangeRateProvider.version,
        base_currency="USD",
        quote_currency="CNY",
        rate_date=rate_date,
        rate=(cny_per_eur / usd_per_eur).quantize(RATE_SCALE, rounding=ROUND_HALF_UP),
        observed_at=datetime.now(UTC),
        raw_payload=payload,
        source_url=source_url,
        mime_type=mime_type,
        confidence=Decimal("0.9900"),
    )
