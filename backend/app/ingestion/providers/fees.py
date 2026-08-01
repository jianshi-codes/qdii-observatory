"""Fund fee schedule provider for portfolio enrichment."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from backend.app.ingestion.http import ProviderHttpClient
from backend.app.ingestion.providers.base import FundFeeObservation, ProviderSchemaError
from backend.app.ingestion.providers.limits import _decode_html, _plain_text


class EastmoneyFundFeeProvider:
    """Reference fee schedule; platform-specific discounts remain separately user-maintained."""

    name = "EASTMONEY_FUND_FEE"
    version = "fund-fee-html-v1"
    endpoint_template = "https://fundf10.eastmoney.com/jjfl_{share_code}.html"

    def __init__(self, http: ProviderHttpClient) -> None:
        self.http = http

    def fetch(self, share_code: str) -> FundFeeObservation:
        if len(share_code) != 6 or not share_code.isdigit():
            raise ValueError(f"Invalid fund share code: {share_code!r}")
        url = self.endpoint_template.format(share_code=share_code)
        response = self.http.request(
            "GET",
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Referer": f"https://fund.eastmoney.com/{share_code}.html",
            },
        )
        return parse_eastmoney_fee_page(
            response.content,
            share_code,
            source_url=str(response.url),
            mime_type=response.headers.get("content-type", "text/html").split(";", 1)[0],
        )


def parse_eastmoney_fee_page(
    payload: bytes,
    share_code: str,
    *,
    source_url: str,
    mime_type: str = "text/html",
) -> FundFeeObservation:
    text = _decode_html(payload)
    if re.search(rf"\({re.escape(share_code)}\)", text) is None:
        raise ProviderSchemaError("Eastmoney fee page does not match the requested share")
    management = _annual_fee(text, "管理费率")
    custody = _annual_fee(text, "托管费率")
    sales_service = _annual_fee(text, "销售服务费率", required=False)
    if management is None or custody is None:
        raise ProviderSchemaError("Eastmoney fee page is missing management or custody fee")

    purchase = re.search(
        r"购买手续费：\s*<b\b[^>]*>(?P<standard>[\d.]+)%</b>\s*&nbsp;\s*"
        r"<b\b[^>]*>(?P<discount>[\d.]+)%</b>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    return FundFeeObservation(
        provider_name=EastmoneyFundFeeProvider.name,
        provider_version=EastmoneyFundFeeProvider.version,
        share_code=share_code,
        observed_at=datetime.now(UTC),
        management_fee_pct_annual=management,
        custody_fee_pct_annual=custody,
        sales_service_fee_pct_annual=sales_service,
        standard_purchase_fee_pct=(
            _percent(purchase.group("standard")) if purchase is not None else None
        ),
        discounted_purchase_fee_pct=(
            _percent(purchase.group("discount")) if purchase is not None else None
        ),
        raw_payload=payload,
        source_url=source_url,
        mime_type=mime_type,
        confidence=Decimal("0.9500"),
    )


def _annual_fee(text: str, label: str, *, required: bool = True) -> Decimal | None:
    match = re.search(
        rf"{re.escape(label)}\s*</td>\s*<td\b[^>]*>(.*?)</td>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if match is None:
        if not required:
            return None
        raise ProviderSchemaError(f"Eastmoney fee page is missing {label}")
    value = _plain_text(match.group(1))
    if value in {"", "-", "--", "---"}:
        return None
    percent = re.search(r"([\d.]+)%", value)
    if percent is None:
        raise ProviderSchemaError(f"Eastmoney fee page has invalid {label}: {value!r}")
    return _percent(percent.group(1))


def _percent(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ProviderSchemaError(f"Invalid fee percentage: {value!r}") from error
    if result < 0 or result > 100:
        raise ProviderSchemaError(f"Fee percentage is outside 0..100: {value!r}")
    return result
