"""Daily purchase-limit providers with source-specific, fail-closed parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from html import unescape
from io import BytesIO
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pdfplumber
from pypdf import PdfReader

from backend.app.ingestion.http import ProviderHttpClient
from backend.app.ingestion.providers.base import (
    ProviderSchemaError,
    PurchaseLimitRecord,
    PurchaseLimitSnapshot,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
TAG = re.compile(r"<[^>]+>")
WHITESPACE = re.compile(r"\s+")
ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
NOTICE_LINK = re.compile(
    r"<a\b[^>]*href=[\"'](?P<href>[^\"']*instance_show_pdf_id\.do\?instanceid=[^\"']+)"
    r"[\"'][^>]*>(?P<title>.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
DATE_TOKEN = re.compile(r"(?P<year>20\d{2})[年/-](?P<month>\d{1,2})[月/-](?P<day>\d{1,2})日?")
PdfTableRow = tuple[str | None, ...]
TableAmountSlot = tuple[str | None, str | None]


def _decode_html(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ProviderSchemaError("Purchase-limit page is neither UTF-8 nor GB18030")


def _plain_text(fragment: str) -> str:
    return WHITESPACE.sub(" ", unescape(TAG.sub(" ", fragment))).strip()


def _compact_text(value: str) -> str:
    return WHITESPACE.sub("", value).replace("，", ",").replace("（", "(").replace("）", ")")


def _money(value: str, unit: str) -> tuple[Decimal, str]:
    try:
        amount = Decimal(value.replace(",", ""))
    except InvalidOperation as error:
        raise ProviderSchemaError(f"Invalid purchase-limit amount: {value!r}") from error
    currency = "CNY"
    multiplier = Decimal("1")
    if unit in {"万", "万元"}:
        multiplier = Decimal("10000")
    elif unit in {"亿", "亿元"}:
        multiplier = Decimal("100000000")
    elif unit == "美元":
        currency = "USD"
    elif unit == "港元":
        currency = "HKD"
    elif unit != "元":
        raise ProviderSchemaError(f"Unsupported purchase-limit currency unit: {unit!r}")
    amount *= multiplier
    if amount <= 0:
        raise ProviderSchemaError("Purchase-limit amount must be positive")
    return amount, currency


def _date_from_match(match: re.Match[str]) -> date:
    return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))


def _published_at(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime(value.year, value.month, value.day, tzinfo=SHANGHAI)


class EastmoneyPurchaseLimitProvider:
    """Current terms offered by the named distributor 天天基金, not all distributors."""

    name = "EASTMONEY_TIANTIAN_PURCHASE_LIMIT"
    version = "fund-fee-html-v1"
    endpoint_template = "https://fundf10.eastmoney.com/jjfl_{share_code}.html"

    def __init__(self, http: ProviderHttpClient) -> None:
        self.http = http

    def fetch(self, share_code: str) -> PurchaseLimitSnapshot:
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
        text = _decode_html(response.content)
        if re.search(rf"\({re.escape(share_code)}\)", text) is None:
            raise ProviderSchemaError(
                "Eastmoney purchase-limit page does not match the requested share"
            )
        record = _parse_eastmoney_page(text, share_code)
        return PurchaseLimitSnapshot(
            provider_name=self.name,
            provider_version=self.version,
            observed_at=datetime.now(UTC),
            records=(record,),
            raw_payload=response.content,
            source_url=str(response.url),
            mime_type=response.headers.get("content-type", "text/html").split(";", 1)[0],
            artifact_type="PURCHASE_LIMIT_HTML",
        )


def _parse_eastmoney_page(text: str, share_code: str) -> PurchaseLimitRecord:
    plain = _plain_text(text)
    status_cell = re.search(
        r"申购状态\s*</(?:td|th)>\s*<td\b[^>]*>(.*?)</td>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    status_match = re.search(r"申购状态\s*(限大额|开放申购|暂停申购|封闭期|场内交易|不支持)", plain)
    if status_match is None:
        status_match = re.search(
            r"交易状态[:：]\s*(限大额|开放申购|暂停申购|封闭期|场内交易|不支持)",
            plain,
        )
    if status_match is None:
        status_cell_value = _plain_text(status_cell.group(1)) if status_cell else ""
        if status_cell_value:
            raise ProviderSchemaError(
                f"Eastmoney page has an unrecognized purchase status: {status_cell_value!r}"
            )
        status_label = re.search(r"申购状态|交易状态[:：]", plain)
        if status_label is None:
            raise ProviderSchemaError("Eastmoney page is missing the purchase-status field")
        status = "UNKNOWN"
        status_start, status_end = status_label.span()
    else:
        status = status_match.group(1)
        status_start, status_end = status_match.span()
    availability = {
        "限大额": "OPEN",
        "开放申购": "OPEN",
        "暂停申购": "PAUSED",
        "封闭期": "PAUSED",
        "场内交易": "NOT_SOLD",
        "不支持": "NOT_SOLD",
        "UNKNOWN": "UNKNOWN",
    }[status]

    amount_match = re.search(
        r"(?:日累计申购限额|单日累计购买上限)\s*([\d,.]+)\s*(亿元|万元|万|元|美元|港元)",
        plain,
    )
    unlimited = re.search(r"日累计申购限额\s*无限额", plain) is not None
    amount: Decimal | None = None
    currency = "CNY"
    if amount_match is not None:
        raw_amount = Decimal(amount_match.group(1).replace(",", ""))
        if raw_amount == 0:
            _, currency = _money("1", amount_match.group(2))
            cap_state = "UNKNOWN"
            if availability == "OPEN":
                availability = "UNKNOWN"
        else:
            amount, currency = _money(amount_match.group(1), amount_match.group(2))
            cap_state = "LIMITED"
    elif unlimited:
        cap_state = "UNLIMITED"
    else:
        cap_state = "UNKNOWN"

    start = max(0, status_start - 80)
    end = min(len(plain), (amount_match.end() if amount_match else status_end) + 120)
    return PurchaseLimitRecord(
        share_code=share_code,
        channel_type="DISTRIBUTION",
        channel_key="EASTMONEY_TIANTIAN",
        channel_name="天天基金",
        business_type="PURCHASE",
        availability_state=availability,
        cap_state=cap_state,
        limit_amount=amount,
        currency=currency,
        limit_basis="PER_ACCOUNT_PER_DAY",
        limit_scope="PER_SHARE",
        effective_from=None,
        effective_to=None,
        source_published_at=None,
        raw_text=plain[start:end],
        confidence=Decimal("0.9500"),
    )


@dataclass(frozen=True, slots=True)
class _NoticeCandidate:
    title: str
    document_url: str
    published_date: date | None
    instance_id: int


class CsrcPurchaseLimitProvider:
    """Latest persistent large-purchase notice from the CSRC EID fund page."""

    name = "CSRC_EID_PURCHASE_LIMIT"
    version = "fund-detail-pdf-v3"
    base_url = "http://eid.csrc.gov.cn/fund/disclose/"
    index_url = urljoin(base_url, "index.html")

    def __init__(self, http: ProviderHttpClient) -> None:
        self.http = http

    def fetch(
        self,
        fund_code: str,
        share_codes: tuple[str, ...],
        *,
        exchange_traded_codes: frozenset[str] = frozenset(),
        share_currencies: dict[str, str] | None = None,
    ) -> PurchaseLimitSnapshot:
        if len(fund_code) != 6 or not fund_code.isdigit():
            raise ValueError(f"Invalid fund code: {fund_code!r}")
        if not share_codes or any(len(code) != 6 or not code.isdigit() for code in share_codes):
            raise ValueError("share_codes must contain six-digit codes")
        validate_url = urljoin(self.base_url, "validate_fund.do")
        validation = self.http.request(
            "POST",
            validate_url,
            data={"cFundCode": fund_code},
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": self.index_url,
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            validation_data = json.loads(validation.content)
        except json.JSONDecodeError as error:
            raise ProviderSchemaError("CSRC fund validation response is not JSON") from error
        if not isinstance(validation_data, dict) or validation_data.get("isSuccess") is not True:
            raise ProviderSchemaError(
                f"CSRC does not recognize fund code {fund_code}: {validation_data!r}"
            )
        fund_id = validation_data.get("fundId")
        if not isinstance(fund_id, (int, str)) or not str(fund_id).isdigit():
            raise ProviderSchemaError("CSRC validation response has no numeric fundId")

        page_url = urljoin(self.base_url, f"fund_detail_search.do?cFundCode={fund_id}")
        page = self.http.request(
            "GET",
            page_url,
            headers={"Accept": "text/html,application/xhtml+xml", "Referer": self.index_url},
        )
        html = _decode_html(page.content)
        candidates = _notice_candidates(html, str(page.url))
        observed_at = datetime.now(UTC)
        observed_date = observed_at.astimezone(SHANGHAI).date()
        for candidate in candidates[:8]:
            document = self.http.request(
                "GET",
                candidate.document_url,
                headers={"Accept": "application/pdf", "Referer": str(page.url)},
            )
            if not document.content.startswith(b"%PDF-"):
                raise ProviderSchemaError("CSRC purchase-limit notice is not a PDF")
            notice_text = _extract_pdf_text(document.content)
            table_rows = _extract_pdf_tables(document.content)
            effective_from = _effective_date(notice_text)
            if effective_from is not None and effective_from > observed_date:
                continue
            records = _parse_csrc_notice(
                notice_text,
                share_codes,
                exchange_traded_codes=exchange_traded_codes,
                share_currencies=share_currencies,
                table_rows=table_rows,
                as_of_date=observed_date,
                fallback_published_date=candidate.published_date,
            )
            return PurchaseLimitSnapshot(
                provider_name=self.name,
                provider_version=self.version,
                observed_at=observed_at,
                records=records,
                raw_payload=document.content,
                source_url=str(document.url),
                mime_type=document.headers.get("content-type", "application/pdf").split(";", 1)[0],
                artifact_type="PURCHASE_LIMIT_NOTICE_PDF",
            )

        records = tuple(
            _unknown_direct_record(code, code in exchange_traded_codes, "未发现适用的大额申购公告")
            for code in share_codes
        )
        return PurchaseLimitSnapshot(
            provider_name=self.name,
            provider_version=self.version,
            observed_at=observed_at,
            records=records,
            raw_payload=page.content,
            source_url=str(page.url),
            mime_type=page.headers.get("content-type", "text/html").split(";", 1)[0],
            artifact_type="PURCHASE_LIMIT_DISCOVERY_HTML",
        )


def _notice_candidates(html: str, page_url: str) -> list[_NoticeCandidate]:
    result: list[_NoticeCandidate] = []
    for row_match in ROW.finditer(html):
        row_html = row_match.group(1)
        link = NOTICE_LINK.search(row_html)
        if link is None:
            continue
        title = _plain_text(link.group("title"))
        compact = _compact_text(title)
        if "节假日" in compact:
            continue
        is_large_purchase_notice = "大额申购" in compact
        is_purchase_cap_notice = "申购" in compact and "业务上限" in compact
        if not (is_large_purchase_notice or is_purchase_cap_notice):
            continue
        if not any(token in compact for token in ("调整", "限制", "暂停", "恢复")):
            continue
        date_match = DATE_TOKEN.search(_plain_text(row_html))
        document_url = urljoin(page_url, unescape(link.group("href")))
        instance_match = re.search(r"[?&]instanceid=(\d+)", document_url)
        if instance_match is None:
            raise ProviderSchemaError("CSRC purchase-limit link has no numeric instance id")
        result.append(
            _NoticeCandidate(
                title=title,
                document_url=document_url,
                published_date=_date_from_match(date_match) if date_match else None,
                instance_id=int(instance_match.group(1)),
            )
        )
    return sorted(
        result,
        key=lambda item: (item.published_date or date.min, item.instance_id),
        reverse=True,
    )


def _extract_pdf_text(payload: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(payload))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as error:
        raise ProviderSchemaError(f"Unable to read CSRC purchase-limit PDF: {error}") from error
    if not text.strip():
        raise ProviderSchemaError("CSRC purchase-limit PDF contains no extractable text")
    return WHITESPACE.sub(" ", text).strip()


def _extract_pdf_tables(payload: bytes) -> tuple[PdfTableRow, ...]:
    try:
        rows: list[PdfTableRow] = []
        with pdfplumber.open(BytesIO(payload)) as document:
            for page in document.pages:
                for table in page.extract_tables():
                    rows.extend(
                        tuple(cell if cell is None else str(cell) for cell in row) for row in table
                    )
    except Exception as error:
        raise ProviderSchemaError(
            f"Unable to read tables from CSRC purchase-limit PDF: {error}"
        ) from error
    return tuple(rows)


def _effective_date(text: str) -> date | None:
    compact = _compact_text(text)
    for pattern in (
        r"(?:调整|暂停|恢复)[^。]{0,30}起始日(?P<value>20\d{2}年\d{1,2}月\d{1,2}日)",
        r"自(?P<value>20\d{2}年\d{1,2}月\d{1,2}日)起",
    ):
        match = re.search(pattern, compact)
        if match is not None:
            value_match = DATE_TOKEN.search(match.group("value"))
            if value_match is not None:
                return _date_from_match(value_match)
    return None


def _publication_date(text: str) -> date | None:
    compact = _compact_text(text)
    match = re.search(r"公告送出日期[:：]?(20\d{2}年\d{1,2}月\d{1,2}日)", compact)
    if match is None:
        return None
    date_match = DATE_TOKEN.search(match.group(1))
    return _date_from_match(date_match) if date_match else None


def _channel_amounts(compact: str, pattern: str) -> dict[str, tuple[Decimal, str]]:
    channel_matches = list(re.finditer(pattern, compact))
    result: dict[str, tuple[Decimal, str]] = {}
    for channel_match in channel_matches:
        segment = compact[channel_match.end() : channel_match.end() + 500]
        segment = re.split(r"[。；;]", segment, maxsplit=1)[0]
        match = re.search(
            r"(?:不应超过|应不超过|不超过|累计金额为|上限为)"
            r"(?:人民币)?"
            r"([\d,.]+)(亿元|万元|万|元|美元|港元)",
            segment,
        )
        if match is None:
            continue
        amount = _money(match.group(1), match.group(2))
        previous = result.get(amount[1])
        if previous is not None and previous != amount:
            raise ProviderSchemaError(
                f"Conflicting {amount[1]} purchase limits for the same sales channel"
            )
        result[amount[1]] = amount
    return result


def _table_currency_unit(value: str | None) -> str | None:
    compact = _compact_text(value or "")
    if compact in {"人民币", "人民币元", "元人民币", "元"}:
        return "元"
    if compact in {"人民币万", "人民币万元", "万元", "万"}:
        return "万元"
    if compact == "美元":
        return "美元"
    if compact == "港元":
        return "港元"
    return None


def _table_label_unit(label: str) -> str | None:
    match = re.search(
        r"单位[:：]?(人民币万元|人民币元|万元|元|美元|港元)",
        _compact_text(label),
    )
    return _table_currency_unit(match.group(1)) if match else None


def _table_amount(
    value: str,
    *,
    default_unit: str,
) -> tuple[Decimal, str] | None:
    compact = _compact_text(value)
    if compact in {"-", "—", "不适用"}:
        return None
    match = re.fullmatch(
        r"([\d,.]+)(人民币万元|人民币元|元人民币|万元|万|元|美元|港元)?",
        compact,
    )
    if match is None:
        return None
    unit = _table_currency_unit(match.group(2)) if match.group(2) else default_unit
    if unit is None:
        return None
    return _money(match.group(1), unit)


def _table_limits(
    rows: tuple[PdfTableRow, ...],
    text: str,
    share_codes: tuple[str, ...],
    share_currencies: dict[str, str],
) -> dict[str, dict[str, tuple[Decimal, str]]]:
    requested = set(share_codes)
    compact_text = _compact_text(text)
    units_follow_share_currency = (
        "人民币份额的限制金额单位为人民币元" in compact_text
        and "美元份额的限制金额单位为美元" in compact_text
    )
    code_candidates: list[tuple[str, ...]] = []
    for row in rows:
        codes = tuple(
            compact
            for cell in row
            if re.fullmatch(r"\d{6}", compact := _compact_text(cell or ""))
        )
        if codes and requested.intersection(codes):
            code_candidates.append(codes)
    if code_candidates:
        codes = max(code_candidates, key=len)
    else:
        mentioned = tuple(code for code in share_codes if code in text)
        codes = mentioned or (share_codes if len(share_codes) == 1 else ())
    if not codes:
        return {}

    units: tuple[str, ...] = ()
    for row in rows:
        compact_cells = tuple(_compact_text(cell or "") for cell in row)
        if not any("金额单位" in cell for cell in compact_cells):
            continue
        parsed_units = tuple(
            unit for cell in row if (unit := _table_currency_unit(cell)) is not None
        )
        if len(parsed_units) == len(codes):
            units = parsed_units
            break

    candidates: dict[str, list[tuple[int, tuple[TableAmountSlot, ...]]]] = {
        "PURCHASE": [],
        "RECURRING_INVESTMENT": [],
    }
    for row in rows:
        compact_cells = tuple(_compact_text(cell or "") for cell in row)
        joined = "".join(compact_cells)
        if "限制定期定额" in joined and "金额" in joined:
            business_type = "RECURRING_INVESTMENT"
        elif re.search(r"限制(?:大额)?申购金额", joined):
            business_type = "PURCHASE"
        else:
            continue
        slots: list[TableAmountSlot] = []
        current_unit: str | None = None
        found_label = False
        for cell, compact in zip(row, compact_cells, strict=True):
            if "限制" in compact and "金额" in compact:
                found_label = True
                current_unit = _table_label_unit(cell or "") or current_unit
                inline = re.search(
                    r"金额[:：]([\d,.]+(?:人民币万元|人民币元|元人民币|万元|万|元|美元|港元)?)",
                    compact,
                )
                if inline:
                    slots.append((inline.group(1), current_unit))
                continue
            if not found_label:
                continue
            if not compact:
                continue
            if compact in {"-", "—", "不适用"}:
                slots.append((None, current_unit))
            elif re.fullmatch(
                r"[\d,.]+(?:人民币万元|人民币元|元人民币|万元|万|元|美元|港元)?",
                compact,
            ):
                slots.append((cell, current_unit))
        if slots:
            exact = 1 if len(slots) == len(codes) else 0
            candidates[business_type].append((exact, tuple(slots)))

    result: dict[str, dict[str, tuple[Decimal, str]]] = {}
    for business_type, options in candidates.items():
        if not options:
            continue
        _, selected_slots = max(
            options,
            key=lambda item: (
                item[0],
                sum(value is not None for value, _ in item[1]),
            ),
        )
        if len(selected_slots) == 1 and len(codes) > 1:
            selected_slots = selected_slots * len(codes)
        if len(selected_slots) != len(codes):
            raise ProviderSchemaError(
                f"CSRC table has {len(selected_slots)} {business_type} limits "
                f"for {len(codes)} shares"
            )
        parsed: dict[str, tuple[Decimal, str]] = {}
        for index, (share_code, (value, slot_unit)) in enumerate(
            zip(codes, selected_slots, strict=True)
        ):
            if share_code not in requested:
                continue
            if value is None:
                continue
            share_unit = {"CNY": "元", "USD": "美元", "HKD": "港元"}.get(
                share_currencies.get(share_code, "CNY"), "元"
            )
            if units:
                default_unit = units[index]
            elif units_follow_share_currency:
                default_unit = share_unit
            else:
                default_unit = slot_unit or share_unit
            amount = _table_amount(value, default_unit=default_unit)
            if amount is None:
                raise ProviderSchemaError(
                    f"Unable to parse {business_type} table limit for {share_code}"
                )
            expected_currency = share_currencies.get(share_code)
            if expected_currency is not None and amount[1] != expected_currency:
                raise ProviderSchemaError(
                    f"CSRC table currency {amount[1]} does not match "
                    f"{share_code} currency {expected_currency}"
                )
            parsed[share_code] = amount
        if parsed:
            result[business_type] = parsed
    return result


def _notice_headline(compact: str) -> str:
    return re.split(r"公告送出日期", compact, maxsplit=1)[0]


def _is_restoration_notice(compact: str) -> bool:
    headline = _notice_headline(compact)
    return "恢复大额申购" in headline or "恢复正常办理大额申购" in headline


def _restoration_date(text: str) -> date | None:
    compact = _compact_text(text)
    match = re.search(
        r"自(?P<value>20\d{2}年\d{1,2}月\d{1,2}日)起[^。]{0,50}(?:将)?恢复(?:正常)?办理?大额申购",
        compact,
    )
    if match is None:
        return None
    date_match = DATE_TOKEN.search(match.group("value"))
    return _date_from_match(date_match) if date_match else None


def _parse_csrc_notice(
    text: str,
    share_codes: tuple[str, ...],
    *,
    exchange_traded_codes: frozenset[str],
    share_currencies: dict[str, str] | None,
    table_rows: tuple[PdfTableRow, ...],
    as_of_date: date,
    fallback_published_date: date | None,
) -> tuple[PurchaseLimitRecord, ...]:
    compact = _compact_text(text)
    effective_from = _effective_date(text)
    published_date = _publication_date(text) or fallback_published_date
    combined_scope = re.search(r"(?:各|两|二)类份额.{0,20}(?:加总|合并)", compact) is not None
    scope = "ALL_SHARES_COMBINED" if combined_scope else "PER_SHARE"
    currencies = share_currencies or {code: "CNY" for code in share_codes}
    table_limits = _table_limits(table_rows, text, share_codes, currencies)
    business_types = ["PURCHASE"]
    if "定期定额" in compact:
        business_types.append("RECURRING_INVESTMENT")
    if "转换转入" in compact:
        business_types.append("CONVERSION_IN")

    for business_type in table_limits:
        if business_type not in business_types:
            business_types.append(business_type)
    combined_amounts = _channel_amounts(
        compact,
        r"通过(?:所有销售机构和本公司直销(?:渠道|机构)|本公司直销(?:渠道|机构)和所有销售机构)",
    )
    direct_amounts = _channel_amounts(
        compact,
        r"通过本公司直销(?:渠道|机构)",
    )
    distribution_amounts = _channel_amounts(compact, r"通过(?:各|所有)?代销机构")
    if combined_amounts:
        direct_amounts = combined_amounts
        distribution_amounts = combined_amounts
    elif not direct_amounts and not distribution_amounts:
        combined_amounts = _channel_amounts(
            compact,
            r"人民币销售(?:的)?(?:申购|业务)",
        )
        if combined_amounts:
            direct_amounts = combined_amounts
            distribution_amounts = combined_amounts

    restoration_date = _restoration_date(text)
    restored = _is_restoration_notice(compact) and (
        restoration_date is None or restoration_date <= as_of_date
    )
    if restored and restoration_date is not None:
        effective_from = restoration_date
    full_pause = re.search(r"(?<!大额)暂停申购(?:、|及|和|业务)", compact) is not None
    direct_only_table = "直销" in _notice_headline(compact)
    mentioned_codes = {code for code in share_codes if code in compact}
    applicable_codes = mentioned_codes or set(share_codes)
    excerpt = text[:2000]
    records: list[PurchaseLimitRecord] = []
    for share_code in share_codes:
        if share_code not in applicable_codes:
            records.append(
                _unknown_direct_record(
                    share_code,
                    share_code in exchange_traded_codes,
                    "最新公告未明确覆盖该份额代码",
                    published_at=_published_at(published_date),
                    effective_from=effective_from,
                )
            )
            continue
        share_currency = currencies.get(share_code, "CNY")
        for business_type in business_types:
            table_amount = table_limits.get(business_type, {}).get(share_code)
            if restored:
                direct_amount = None
                distribution_amount = None
            elif combined_amounts:
                direct_amount = combined_amounts.get(share_currency)
                distribution_amount = combined_amounts.get(share_currency)
            else:
                direct_amount = direct_amounts.get(share_currency) or table_amount
                distribution_amount = distribution_amounts.get(share_currency)
                if distribution_amount is None and not direct_only_table:
                    distribution_amount = table_amount
            records.append(
                _official_record(
                    share_code=share_code,
                    channel_type="DIRECT",
                    channel_key="DIRECT",
                    channel_name="基金管理人直销",
                    business_type=business_type,
                    amount=direct_amount,
                    restored=restored,
                    full_pause=full_pause,
                    limit_scope=scope,
                    effective_from=effective_from,
                    published_at=_published_at(published_date),
                    raw_text=excerpt,
                    not_applicable=share_code in exchange_traded_codes,
                )
            )
            if (
                distribution_amount is not None
                or combined_amounts
                or (restored and not direct_only_table)
            ):
                records.append(
                    _official_record(
                        share_code=share_code,
                        channel_type="DISTRIBUTION",
                        channel_key="ALL_DISTRIBUTORS",
                        channel_name="全部代销机构（公告明确）",
                        business_type=business_type,
                        amount=distribution_amount,
                        restored=restored,
                        full_pause=full_pause,
                        limit_scope=scope,
                        effective_from=effective_from,
                        published_at=_published_at(published_date),
                        raw_text=excerpt,
                        not_applicable=False,
                    )
                )
    return tuple(records)


def _official_record(
    *,
    share_code: str,
    channel_type: str,
    channel_key: str,
    channel_name: str,
    business_type: str,
    amount: tuple[Decimal, str] | None,
    restored: bool,
    full_pause: bool,
    limit_scope: str,
    effective_from: date | None,
    published_at: datetime | None,
    raw_text: str,
    not_applicable: bool,
) -> PurchaseLimitRecord:
    if not_applicable:
        availability = "NOT_APPLICABLE"
        cap_state = "UNKNOWN"
        limit_amount = None
        currency = "CNY"
    else:
        availability = "PAUSED" if full_pause else "OPEN" if (amount or restored) else "UNKNOWN"
        if amount is not None:
            cap_state = "LIMITED"
            limit_amount, currency = amount
        elif restored:
            cap_state = "UNLIMITED"
            limit_amount = None
            currency = "CNY"
        else:
            cap_state = "UNKNOWN"
            limit_amount = None
            currency = "CNY"
    confidence = Decimal("0.9900") if amount is not None else Decimal("0.7000")
    return PurchaseLimitRecord(
        share_code=share_code,
        channel_type=channel_type,
        channel_key=channel_key,
        channel_name=channel_name,
        business_type=business_type,
        availability_state=availability,
        cap_state=cap_state,
        limit_amount=limit_amount,
        currency=currency,
        limit_basis="PER_ACCOUNT_PER_DAY",
        limit_scope=limit_scope,
        effective_from=effective_from,
        effective_to=None,
        source_published_at=published_at,
        raw_text=raw_text,
        confidence=confidence,
    )


def _unknown_direct_record(
    share_code: str,
    not_applicable: bool,
    reason: str,
    *,
    published_at: datetime | None = None,
    effective_from: date | None = None,
) -> PurchaseLimitRecord:
    return PurchaseLimitRecord(
        share_code=share_code,
        channel_type="DIRECT",
        channel_key="DIRECT",
        channel_name="基金管理人直销",
        business_type="PURCHASE",
        availability_state="NOT_APPLICABLE" if not_applicable else "UNKNOWN",
        cap_state="UNKNOWN",
        limit_amount=None,
        currency="CNY",
        limit_basis="PER_ACCOUNT_PER_DAY",
        limit_scope="UNKNOWN",
        effective_from=effective_from,
        effective_to=None,
        source_published_at=published_at,
        raw_text=reason,
        confidence=Decimal("1.0000") if not_applicable else Decimal("0.5000"),
    )
