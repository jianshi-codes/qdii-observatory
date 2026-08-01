"""Provider-neutral domain records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


class ProviderSchemaError(ValueError):
    """Raised when an upstream response no longer matches its validated schema."""


@dataclass(frozen=True, slots=True)
class ReportCandidate:
    provider_name: str
    provider_version: str
    fund_code: str
    title: str
    public_available_at: datetime | None
    source_page_url: str
    document_url: str
    mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class NavRecord:
    nav_date: date
    unit_nav: Decimal
    accumulated_nav: Decimal | None
    published_daily_return_pct: Decimal | None
    source_published_at: datetime | None


@dataclass(frozen=True, slots=True)
class NavPage:
    provider_name: str
    provider_version: str
    share_code: str
    page_index: int
    total_pages: int
    total_records: int
    records: tuple[NavRecord, ...]
    raw_payload: bytes
    source_url: str
    mime_type: str


@dataclass(frozen=True, slots=True)
class ExchangePriceRecord:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    pct_change: Decimal | None
    volume: Decimal | None
    turnover: Decimal | None


@dataclass(frozen=True, slots=True)
class PurchaseLimitRecord:
    """One source-scoped purchase-limit observation for one fund share."""

    share_code: str
    channel_type: str
    channel_key: str
    channel_name: str
    business_type: str
    availability_state: str
    cap_state: str
    limit_amount: Decimal | None
    currency: str
    limit_basis: str
    limit_scope: str
    effective_from: date | None
    effective_to: date | None
    source_published_at: datetime | None
    raw_text: str
    confidence: Decimal | None


@dataclass(frozen=True, slots=True)
class PurchaseLimitSnapshot:
    """Validated records plus the exact source response used to derive them."""

    provider_name: str
    provider_version: str
    observed_at: datetime
    records: tuple[PurchaseLimitRecord, ...]
    raw_payload: bytes
    source_url: str
    mime_type: str
    artifact_type: str


@dataclass(frozen=True, slots=True)
class FundFeeObservation:
    """Validated fund-share fee schedule from one observed source page."""

    provider_name: str
    provider_version: str
    share_code: str
    observed_at: datetime
    management_fee_pct_annual: Decimal | None
    custody_fee_pct_annual: Decimal | None
    sales_service_fee_pct_annual: Decimal | None
    standard_purchase_fee_pct: Decimal | None
    discounted_purchase_fee_pct: Decimal | None
    raw_payload: bytes
    source_url: str
    mime_type: str
    confidence: Decimal | None


@dataclass(frozen=True, slots=True)
class ExchangeRateObservation:
    """One direct or cross rate with exact source material."""

    provider_name: str
    provider_version: str
    base_currency: str
    quote_currency: str
    rate_date: date
    rate: Decimal
    observed_at: datetime
    raw_payload: bytes
    source_url: str
    mime_type: str
    confidence: Decimal | None


class ReportProvider(Protocol):
    name: str
    version: str

    def discover(self, fund_code: str, year: int, quarter: int) -> list[ReportCandidate]: ...

    def download(self, candidate: ReportCandidate) -> bytes: ...


class NavProvider(Protocol):
    name: str
    version: str

    def fetch_page(
        self,
        share_code: str,
        page_index: int,
        page_size: int,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> NavPage: ...


class MarketPriceProvider(Protocol):
    name: str
    version: str

    def fetch(
        self, share_code: str, start_date: date, end_date: date
    ) -> tuple[bytes, tuple[ExchangePriceRecord, ...], str]: ...


class PurchaseLimitProvider(Protocol):
    name: str
    version: str

    def fetch(self, share_code: str) -> PurchaseLimitSnapshot: ...


class FundFeeProvider(Protocol):
    name: str
    version: str

    def fetch(self, share_code: str) -> FundFeeObservation: ...


class ExchangeRateProvider(Protocol):
    name: str
    version: str

    def fetch(self) -> ExchangeRateObservation: ...
