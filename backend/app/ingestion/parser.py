"""Deterministic semantic parser for Chinese public-fund quarterly PDFs."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from itertools import zip_longest
from typing import Any, Literal

import pdfplumber

PARSER_VERSION = "quarterly-pdf-semantic-v3"
EXPECTED_PERIOD_END = date(2026, 6, 30)
PARSE_TOLERANCE_PCT = Decimal("0.20")
CHINESE = re.compile(r"[\u3400-\u9fff]")
SIX_DIGITS = re.compile(r"(?<![0-9])([0-9]{6})(?![0-9])")

TableKind = Literal["ASSET", "COUNTRY", "INDUSTRY", "SECURITY", "FUND", "IGNORE"]


class ImageOnlyPdfError(ValueError):
    """Raised when the document has no usable text layer."""


class ReportParseError(ValueError):
    """Raised for report identity or semantic parsing failures."""


@dataclass(frozen=True, slots=True)
class ParsedAllocation:
    label_raw: str
    label_normalized: str
    fair_value_cny: Decimal | None
    nav_pct: Decimal | None
    rank: int | None
    source_section: str
    raw_row: dict[str, Any]
    confidence: Decimal


@dataclass(frozen=True, slots=True)
class ParsedSecurityHolding:
    security_code_raw: str | None
    security_name_raw: str
    security_name_normalized: str
    security_name_zh: str | None
    security_name_en: str | None
    exchange_raw: str | None
    market_normalized: str | None
    country_normalized: str | None
    currency: str | None
    quantity: Decimal | None
    fair_value_cny: Decimal | None
    nav_pct: Decimal | None
    rank: int
    security_type: str
    source_section: str
    raw_row: dict[str, Any]
    confidence: Decimal


@dataclass(frozen=True, slots=True)
class ParsedFundHolding:
    fund_code_raw: str | None
    fund_name_raw: str
    fund_name_normalized: str
    fund_type_raw: str | None
    operation_mode_raw: str | None
    manager_raw: str | None
    currency: str | None
    fair_value_cny: Decimal | None
    nav_pct: Decimal | None
    rank: int
    source_section: str
    raw_row: dict[str, Any]
    confidence: Decimal


@dataclass(slots=True)
class ParsedQuarterlyReport:
    fund_name: str
    main_code: str
    manager_name: str
    period_end: date
    benchmark: str | None
    share_codes: tuple[str, ...]
    target_fund_name: str | None
    target_fund_code: str | None
    assets: list[ParsedAllocation] = field(default_factory=list)
    countries: list[ParsedAllocation] = field(default_factory=list)
    industries: list[ParsedAllocation] = field(default_factory=list)
    securities: list[ParsedSecurityHolding] = field(default_factory=list)
    funds: list[ParsedFundHolding] = field(default_factory=list)
    explicit_empty_sections: frozenset[str] = frozenset()
    page_count: int = 0
    text_sha256: str = ""
    parse_confidence: Decimal = Decimal("0")
    quality_issues: list[dict[str, Any]] = field(default_factory=list)


def parse_quarterly_pdf(payload: bytes) -> ParsedQuarterlyReport:
    """Parse one text-layer PDF using headings and geometric table extraction."""

    if not payload.startswith(b"%PDF-"):
        raise ReportParseError("Document does not start with a PDF signature")
    with pdfplumber.open(BytesIO(payload)) as document:
        page_texts = [page.extract_text(layout=True) or "" for page in document.pages]
        if sum(len(text.strip()) for text in page_texts) < 500:
            raise ImageOnlyPdfError("PDF has no usable text layer; OCR requires explicit review")
        parsed = _identity("\n\f\n".join(page_texts))
        parsed.page_count = len(document.pages)
        parsed.text_sha256 = hashlib.sha256("\n\f\n".join(page_texts).encode()).hexdigest()
        _parse_tables(document.pages, parsed)

    _append_unclassified_industry_note("\n".join(page_texts), parsed)
    parsed.explicit_empty_sections = _explicit_empty_sections(page_texts)
    if parsed.target_fund_code and len(parsed.funds) == 1 and parsed.funds[0].fund_code_raw is None:
        original = parsed.funds[0]
        parsed.funds[0] = ParsedFundHolding(
            fund_code_raw=parsed.target_fund_code,
            fund_name_raw=original.fund_name_raw,
            fund_name_normalized=original.fund_name_normalized,
            fund_type_raw=original.fund_type_raw,
            operation_mode_raw=original.operation_mode_raw,
            manager_raw=original.manager_raw,
            currency=original.currency,
            fair_value_cny=original.fair_value_cny,
            nav_pct=original.nav_pct,
            rank=original.rank,
            source_section=original.source_section,
            raw_row=original.raw_row,
            confidence=original.confidence,
        )
    parsed.quality_issues.extend(validate_parsed_report(parsed))
    parsed.parse_confidence = _parse_confidence(parsed)
    return parsed


def _identity(text: str) -> ParsedQuarterlyReport:
    compact = re.sub(r"[ \t]", "", text)
    identity_scope = compact.partition("目标基金基本情况")[0]
    main_code = _capture(identity_scope, r"基金主代码\s*([0-9]{6})", "fund main code")
    manager = _capture(
        compact,
        r"基金管理人[：:]?\s*([^\n]{2,100}?(?:有限责任公司|有限公司))",
        "fund manager",
    )
    period_matches = re.findall(r"(20[0-9]{2})年([0-9]{1,2})月([0-9]{1,2})日", compact)
    period_dates = [date(int(year), int(month), int(day)) for year, month, day in period_matches]
    period_end = next((value for value in period_dates if value == EXPECTED_PERIOD_END), None)
    if period_end is None:
        raise ReportParseError(
            f"Expected report period end {EXPECTED_PERIOD_END.isoformat()} is absent"
        )
    short_name_match = re.search(r"基金简称\s+([^\n]{2,100})", text)
    title_match = re.search(r"\A\s*(.+?)\s*2026\s*年?\s*第?\s*2\s*季度报告", text, re.DOTALL)
    fund_name = (
        _clean_text(short_name_match.group(1))
        if short_name_match
        else _clean_text(title_match.group(1))
        if title_match
        else ""
    )
    benchmark_match = re.search(r"业绩比较基准\s+([^\n]+)", text)
    benchmark = _clean_text(benchmark_match.group(1)) if benchmark_match else None

    share_codes: tuple[str, ...] = ()
    share_match = re.search(r"下属[^\n]{0,40}交易代码(?P<body>.{0,300})", text, re.DOTALL)
    if share_match:
        share_codes = tuple(dict.fromkeys(SIX_DIGITS.findall(share_match.group("body"))))
    note_codes = tuple(
        re.sub(r"\s+", "", value)
        for value in re.findall(r"份额代码[：:]?\s*((?:[0-9]\s*){6})", text)
    )
    share_codes = tuple(dict.fromkeys((*share_codes, *note_codes)))
    if not share_codes:
        share_codes = (main_code,)

    target_name = None
    target_code = None
    target_match = re.search(
        r"目标基金基本情况(?P<body>.*?)(?:目标基金产品说明|§3|主要财务指标)",
        compact,
        re.DOTALL,
    )
    if target_match:
        body = target_match.group("body")
        code_match = re.search(r"基金主代码([0-9]{6})", body)
        name_match = re.search(r"基金名称(.+?)基金主代码", body)
        target_code = code_match.group(1) if code_match else None
        target_name = _clean_text(name_match.group(1)) if name_match else None

    return ParsedQuarterlyReport(
        fund_name=fund_name,
        main_code=main_code,
        manager_name=manager,
        period_end=period_end,
        benchmark=benchmark,
        share_codes=share_codes,
        target_fund_name=target_name,
        target_fund_code=target_code,
    )


def _capture(text: str, pattern: str, label: str) -> str:
    match = re.search(pattern, text)
    if match is None:
        raise ReportParseError(f"Could not identify {label}")
    return _clean_text(match.group(1))


def _parse_tables(pages: list[Any], parsed: ParsedQuarterlyReport) -> None:
    active: TableKind = "IGNORE"
    pending_security: list[str] | None = None
    for page_number, page in enumerate(pages, start=1):
        for table in page.extract_tables():
            if not table:
                continue
            classified = _classify_table(table)
            if classified is not None:
                if active == "SECURITY" and pending_security is not None:
                    _append_security(parsed, pending_security, page_number - 1)
                    pending_security = None
                active = classified
            if active == "ASSET":
                _parse_allocation_table(table, parsed.assets, "报告期末基金资产组合情况", "ASSET")
            elif active == "COUNTRY":
                _parse_allocation_table(
                    table, parsed.countries, "国家（地区）证券市场投资分布", "COUNTRY"
                )
            elif active == "INDUSTRY":
                _parse_allocation_table(table, parsed.industries, "行业分类投资组合", "INDUSTRY")
            elif active == "SECURITY":
                pending_security = _collect_security_rows(
                    table, parsed, pending_security, page_number
                )
            elif active == "FUND":
                _parse_fund_table(table, parsed, page_number)
    if pending_security is not None:
        _append_security(parsed, pending_security, len(pages))


def _classify_table(table: list[list[str | None]]) -> TableKind | None:
    header_rows: list[list[str | None]] = []
    for row in table[:20]:
        values = [_cell(cell) for cell in row if _cell(cell)]
        if values and _integer_or_none(values[0]) is not None:
            break
        header_rows.append(row)
    if not header_rows:
        return None
    row_major = " ".join(_cell(cell) for row in header_rows for cell in row)
    column_major = " ".join(
        _cell(cell)
        for column in zip_longest(*header_rows, fillvalue=None)
        for cell in column
    )
    compact = re.sub(r"\s+", "", f"{row_major} {column_major}")
    compact = compact.replace("(", "（").replace(")", "）")
    if "基金名称" in compact and "基金类型" in compact and "管理人" in compact:
        return "FUND"
    if (
        "公司名" in compact
        and ("证券代" in compact or ("证券" in compact and "代码" in compact))
        and ("数量" in compact or "（股）" in compact)
    ):
        return "SECURITY"
    if "国家（地区）" in compact and "公允价值" in compact:
        return "COUNTRY"
    if "行业类别" in compact and "公允价值" in compact:
        return "INDUSTRY"
    if "项目" in compact and "基金总资产" in compact:
        return "ASSET"
    if any(
        marker in compact
        for marker in (
            "债券代码",
            "债券信用等级",
            "衍生品类别",
            "报告期期初基金份额总额",
            "名称 金额（人民币元）",
        )
    ):
        return "IGNORE"
    return None


def _parse_allocation_table(
    table: list[list[str | None]],
    destination: list[ParsedAllocation],
    section: str,
    kind: Literal["ASSET", "COUNTRY", "INDUSTRY"],
) -> None:
    existing = {(item.label_raw, item.fair_value_cny, item.nav_pct) for item in destination}
    for raw in table:
        values = [_cell(cell) for cell in raw if _cell(cell)]
        if len(values) < 3:
            continue
        rank: int | None = None
        if values[0].isdigit():
            rank = int(values.pop(0))
        label = values[0]
        normalized_label = label.replace("(", "（").replace(")", "）")
        if any(
            marker in normalized_label for marker in ("序号", "国家（地区）", "行业类别", "项目")
        ):
            continue
        if label == "合计":
            continue
        fair_value = _decimal_or_none(values[-2])
        nav_pct = _decimal_or_none(values[-1])
        if fair_value is None and nav_pct is None and kind != "ASSET":
            continue
        key = (label, fair_value, nav_pct)
        if key in existing:
            continue
        destination.append(
            ParsedAllocation(
                label_raw=label,
                label_normalized=_normalize_allocation(label, kind),
                fair_value_cny=fair_value,
                nav_pct=nav_pct,
                rank=rank if rank is not None else len(destination) + 1,
                source_section=section,
                raw_row={"cells": [_cell(cell) for cell in raw]},
                confidence=Decimal("0.98"),
            )
        )
        existing.add(key)


def _collect_security_rows(
    table: list[list[str | None]],
    parsed: ParsedQuarterlyReport,
    pending: list[str] | None,
    page_number: int,
) -> list[str] | None:
    for raw in table:
        values = [_cell(cell) for cell in raw if _cell(cell)]
        if values and _integer_or_none(values[0]) is not None and len(values) >= 9:
            if pending is not None:
                _append_security(parsed, pending, page_number)
            pending = values[:9]
            continue
        if pending is not None and len(raw) == 9 and any(_cell(cell) for cell in raw):
            continuation = [_cell(cell) for cell in raw]
            pending = [
                _merge_fragment(value, continuation[index], numeric=index in {6, 7})
                for index, value in enumerate(pending)
            ]
    return pending


def _append_security(parsed: ParsedQuarterlyReport, values: list[str], page_number: int) -> None:
    if len(values) < 9:
        return
    rank = _integer_or_none(values[0])
    if rank is None:
        return
    if any(item.rank == rank for item in parsed.securities):
        return
    english, chinese, code, exchange, country = values[1:6]
    quantity = _decimal_or_none(values[6])
    fair_value = _decimal_or_none(values[7])
    nav_pct = _decimal_or_none(values[8])
    if fair_value is None or nav_pct is None:
        return
    raw_name = chinese or english
    parsed.securities.append(
        ParsedSecurityHolding(
            security_code_raw=code or None,
            security_name_raw=raw_name,
            security_name_normalized=_normalize_name(raw_name),
            security_name_zh=chinese or None,
            security_name_en=english or None,
            exchange_raw=exchange or None,
            market_normalized=_normalize_market(exchange),
            country_normalized=_normalize_country(country),
            currency=_country_currency(country),
            quantity=quantity,
            fair_value_cny=fair_value,
            nav_pct=nav_pct,
            rank=rank,
            security_type="DEPOSITARY_RECEIPT" if "存托" in raw_name.upper() else "EQUITY",
            source_section="前十名股票及存托凭证投资明细",
            raw_row={"cells": values, "page": page_number},
            confidence=Decimal("0.96"),
        )
    )


def _parse_fund_table(
    table: list[list[str | None]], parsed: ParsedQuarterlyReport, page_number: int
) -> None:
    for raw in table:
        values = [_cell(cell) for cell in raw if _cell(cell)]
        if len(values) < 7 or not values[0].isdigit():
            continue
        rank = int(values[0])
        if any(item.rank == rank for item in parsed.funds):
            continue
        fund_name, fund_type, operation, manager = values[1:5]
        fair_value, nav_pct = _decimal_or_none(values[-2]), _decimal_or_none(values[-1])
        if fair_value is None or nav_pct is None:
            continue
        code_match = SIX_DIGITS.search(fund_name)
        parsed.funds.append(
            ParsedFundHolding(
                fund_code_raw=code_match.group(1) if code_match else None,
                fund_name_raw=fund_name,
                fund_name_normalized=_normalize_name(fund_name),
                fund_type_raw=fund_type or None,
                operation_mode_raw=operation or None,
                manager_raw=manager or None,
                currency=None,
                fair_value_cny=fair_value,
                nav_pct=nav_pct,
                rank=rank,
                source_section="前十名基金投资明细",
                raw_row={"cells": [_cell(cell) for cell in raw], "page": page_number},
                confidence=Decimal("0.96"),
            )
        )


def _explicit_empty_sections(page_texts: list[str]) -> frozenset[str]:
    text = "\n".join(
        line.strip() for page_text in page_texts for line in page_text.splitlines() if line.strip()
    )
    compact_text = re.sub(r"\s+", "", text)
    headings = {
        "COUNTRY": "在各个国家（地区）证券市场的股票及存托凭证投资分布",
        "INDUSTRY": "按行业分类的股票及存托凭证投资组合",
        "SECURITY": "前十名股票及存托凭证",
        "FUND": "前十名基金投资明细",
    }
    empty: set[str] = set()
    for name, heading in headings.items():
        start = compact_text.find(re.sub(r"\s+", "", heading))
        if start < 0:
            continue
        segment = compact_text[start : start + 250]
        if "无。" in segment or re.search(r"本基金本报告期末未持有(?!积极投资)", segment):
            empty.add(name)
    return frozenset(empty)


def _append_unclassified_industry_note(text: str, parsed: ParsedQuarterlyReport) -> None:
    """Preserve the disclosed GICS-unclassified stock amount as an industry row."""

    compact = re.sub(r"\s+", "", text)
    match = re.search(
        r"本报告期末本基金持有的部分股票尚无全球行业分类标准[（(]GICS[）)]，?"
        r"公允价值合计为(?P<fair>[0-9,，.]+)元，?"
        r"占基金资产净值比例合计为(?P<pct>[0-9.]+)[%％]",
        compact,
    )
    if match is None or any(row.label_normalized == "UNCLASSIFIED" for row in parsed.industries):
        return
    fair_value = _decimal_or_none(match.group("fair"))
    nav_pct = _decimal_or_none(match.group("pct"))
    if fair_value is None or nav_pct is None:
        raise ReportParseError("Invalid GICS-unclassified industry disclosure")
    parsed.industries.append(
        ParsedAllocation(
            label_raw="未纳入全球行业分类标准（GICS）",
            label_normalized="UNCLASSIFIED",
            fair_value_cny=fair_value,
            nav_pct=nav_pct,
            rank=len(parsed.industries) + 1,
            source_section="行业分类投资组合脚注",
            raw_row={"text": match.group(0)},
            confidence=Decimal("0.99"),
        )
    )


def validate_parsed_report(parsed: ParsedQuarterlyReport) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for group_name, rows in (
        ("asset", parsed.assets),
        ("country", parsed.countries),
        ("industry", parsed.industries),
        ("security", parsed.securities),
        ("fund", parsed.funds),
    ):
        for row in rows:
            if row.nav_pct is not None and row.nav_pct < 0:
                issues.append(
                    {"code": "NEGATIVE_PERCENTAGE", "section": group_name, "rank": row.rank}
                )
    disclosed = sum((row.nav_pct or Decimal("0")) for row in parsed.securities)
    country_total = sum((row.nav_pct or Decimal("0")) for row in parsed.countries)
    if country_total and disclosed > country_total + PARSE_TOLERANCE_PCT:
        issues.append(
            {
                "code": "TOP_HOLDINGS_EXCEED_EQUITY",
                "disclosed_top10_pct": str(disclosed),
                "equity_country_pct": str(country_total),
            }
        )
    fund_total = sum((row.nav_pct or Decimal("0")) for row in parsed.funds)
    asset_fund = next(
        (row.nav_pct for row in parsed.assets if row.label_normalized == "FUND_INVESTMENT"), None
    )
    if asset_fund is not None and fund_total and abs(fund_total - asset_fund) > Decimal("5"):
        issues.append(
            {
                "code": "FUND_INVESTMENT_RECONCILIATION",
                "holding_nav_pct": str(fund_total),
                "asset_total_asset_pct": str(asset_fund),
                "note": "denominators may differ: NAV versus total assets",
            }
        )
    for section, rows in (
        ("COUNTRY", parsed.countries),
        ("INDUSTRY", parsed.industries),
        ("SECURITY", parsed.securities),
        ("FUND", parsed.funds),
    ):
        if not rows and section not in parsed.explicit_empty_sections:
            issues.append({"code": "EMPTY_WITHOUT_EXPLICIT_DISCLOSURE", "section": section})
    return issues


def derive_metrics(
    parsed: ParsedQuarterlyReport,
) -> dict[str, Decimal | int | bool | date | str | None]:
    countries = _allocation_map(parsed.countries)
    industries = _allocation_map(parsed.industries)
    equity_pct = sum((row.nav_pct or Decimal("0") for row in parsed.countries), Decimal("0"))
    if not parsed.countries and "COUNTRY" in parsed.explicit_empty_sections:
        equity_pct = Decimal("0")
    fund_pct = sum((row.nav_pct or Decimal("0") for row in parsed.funds), Decimal("0"))
    disclosed = sum((row.nav_pct or Decimal("0") for row in parsed.securities), Decimal("0"))
    semiconductor = sum(
        (row.nav_pct or Decimal("0") for row in parsed.securities if _is_semiconductor(row)),
        Decimal("0"),
    )
    tech_total = industries.get("INFORMATION_TECHNOLOGY", Decimal("0")) + industries.get(
        "COMMUNICATION_SERVICES", Decimal("0")
    )
    tech_scope = _derive_tech_scope(parsed, tech_total, semiconductor)
    return {
        "tech_scope": tech_scope,
        "equity_nav_pct": equity_pct,
        "fund_investment_nav_pct": fund_pct,
        "cash_and_other_pct": max(Decimal("0"), Decimal("100") - equity_pct - fund_pct),
        "us_country_pct": countries.get("US"),
        "hong_kong_country_pct": countries.get("HK"),
        "korea_country_pct": countries.get("KR"),
        "taiwan_country_pct": countries.get("TW"),
        "information_technology_pct": industries.get("INFORMATION_TECHNOLOGY"),
        "communication_services_pct": industries.get("COMMUNICATION_SERVICES"),
        "semiconductor_top10_pct": semiconductor,
        "disclosed_top10_pct": disclosed,
        "undisclosed_equity_pct": max(Decimal("0"), equity_pct - disclosed),
        "lookthrough_coverage_pct": None,
        "unresolved_fund_weight_pct": fund_pct if parsed.funds else Decimal("0"),
        "max_lookthrough_depth": 0,
        "circular_relation_detected": False,
        "data_as_of": parsed.period_end,
    }


def _allocation_map(rows: list[ParsedAllocation]) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for row in rows:
        if row.nav_pct is not None:
            result[row.label_normalized] = (
                result.get(row.label_normalized, Decimal("0")) + row.nav_pct
            )
    return result


def _derive_tech_scope(
    parsed: ParsedQuarterlyReport, tech_total: Decimal, semiconductor: Decimal
) -> str:
    identity = f"{parsed.fund_name} {parsed.benchmark or ''}".upper()
    if "中韩" in identity and "半导体" in identity:
        return "CHINA_KOREA_SEMICONDUCTOR"
    if "半导体" in identity or semiconductor >= Decimal("50"):
        return "GLOBAL_SEMICONDUCTOR"
    if "NASDAQ" in identity or "纳斯达克100" in identity or "纳指100" in identity:
        return "NASDAQ_100_MEGA_CAP_GROWTH"
    if tech_total >= Decimal("65"):
        return "GLOBAL_ACTIVE_TECH_HIGH"
    if tech_total >= Decimal("35"):
        return "GLOBAL_ACTIVE_TECH_MIXED"
    if parsed.industries:
        return "GLOBAL_ACTIVE_BROAD"
    return "UNKNOWN"


def _is_semiconductor(row: ParsedSecurityHolding) -> bool:
    text = (
        f"{row.security_name_raw} {row.security_name_en or ''} {row.security_name_zh or ''}".upper()
    )
    keywords = (
        "SEMICONDUCTOR",
        "NVIDIA",
        "MICRON",
        "BROADCOM",
        "MARVELL",
        "INTEL",
        "ASML",
        "TERADYNE",
        "APPLIED MATERIAL",
        "LAM RESEARCH",
        "ADVANCED MICRO",
        "美光",
        "英伟达",
        "半导体",
        "英特尔",
        "超威",
        "应用材料",
        "拉姆研究",
        "科磊",
        "泰瑞达",
    )
    return any(keyword in text for keyword in keywords)


def _parse_confidence(parsed: ParsedQuarterlyReport) -> Decimal:
    score = Decimal("0.45")
    score += Decimal("0.10") if parsed.assets else Decimal("0")
    score += (
        Decimal("0.08")
        if parsed.countries or "COUNTRY" in parsed.explicit_empty_sections
        else Decimal("0")
    )
    score += (
        Decimal("0.08")
        if parsed.industries or "INDUSTRY" in parsed.explicit_empty_sections
        else Decimal("0")
    )
    score += (
        Decimal("0.10")
        if parsed.securities or "SECURITY" in parsed.explicit_empty_sections
        else Decimal("0")
    )
    score += (
        Decimal("0.10")
        if parsed.funds or "FUND" in parsed.explicit_empty_sections
        else Decimal("0")
    )
    score -= Decimal("0.03") * len(parsed.quality_issues)
    return min(Decimal("0.99"), max(Decimal("0"), score))


def _cell(value: str | None) -> str:
    return _clean_text(value or "")


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", value).upper()


def _decimal_or_none(value: str) -> Decimal | None:
    compact = re.sub(r"[\s,，]", "", value).replace("％", "").replace("%", "")
    if compact in {"", "-", "—", "–", "－"}:
        return None
    try:
        return Decimal(compact)
    except InvalidOperation:
        return None


def _integer_or_none(value: str) -> int | None:
    compact = re.sub(r"\s+", "", value)
    return int(compact) if re.fullmatch(r"[0-9]+", compact) else None


def _merge_fragment(value: str, fragment: str, *, numeric: bool) -> str:
    if not fragment:
        return value
    if not value:
        return fragment
    if numeric or CHINESE.search(value + fragment):
        return value + fragment
    return f"{value} {fragment}"


def _normalize_allocation(label: str, kind: Literal["ASSET", "COUNTRY", "INDUSTRY"]) -> str:
    compact = re.sub(r"\s+", "", label)
    mappings: tuple[tuple[str, str], ...]
    if kind == "ASSET":
        mappings = (
            ("权益投资", "EQUITY"),
            ("基金投资", "FUND_INVESTMENT"),
            ("银行存款", "CASH"),
            ("其他资产", "OTHER"),
            ("固定收益", "FIXED_INCOME"),
            ("金融衍生品", "DERIVATIVES"),
        )
    elif kind == "COUNTRY":
        return _normalize_country(compact) or compact.upper()
    else:
        mappings = (
            ("信息技术", "INFORMATION_TECHNOLOGY"),
            ("科技", "INFORMATION_TECHNOLOGY"),
            ("通讯", "COMMUNICATION_SERVICES"),
            ("通信", "COMMUNICATION_SERVICES"),
            ("工业", "INDUSTRIALS"),
            ("医疗保健", "HEALTH_CARE"),
            ("金融", "FINANCIALS"),
            ("非必需消费", "CONSUMER_DISCRETIONARY"),
            ("必需消费", "CONSUMER_STAPLES"),
            ("材料", "MATERIALS"),
            ("基础材料", "MATERIALS"),
            ("能源", "ENERGY"),
            ("公用事业", "UTILITIES"),
            ("房地产", "REAL_ESTATE"),
        )
    for raw, normalized in mappings:
        if raw in compact:
            return normalized
    return compact.upper()


def _normalize_country(value: str) -> str | None:
    compact = re.sub(r"\s+", "", value)
    mappings = (
        (("美国", "USA", "UNITEDSTATES"), "US"),
        (("中国香港", "香港", "HONGKONG"), "HK"),
        (("中国台湾", "台湾", "TAIWAN"), "TW"),
        (("韩国", "KOREA"), "KR"),
        (("中国内地", "中国大陆", "CHINA"), "CN"),
    )
    upper = compact.upper()
    for aliases, normalized in mappings:
        if any(alias.upper() in upper for alias in aliases):
            return normalized
    return upper or None


def _normalize_market(value: str) -> str | None:
    compact = re.sub(r"\s+", "", value).upper()
    mappings = (
        (("纳斯达克", "NASDAQ"), "NASDAQ"),
        (("纽约", "NYSE"), "NYSE"),
        (("香港", "HKEX"), "HKEX"),
        (("韩国", "KRX"), "KRX"),
        (("台湾", "TWSE"), "TWSE"),
    )
    for aliases, normalized in mappings:
        if any(alias in compact for alias in aliases):
            return normalized
    return compact or None


def _country_currency(country: str) -> str | None:
    return {"US": "USD", "HK": "HKD", "TW": "TWD", "KR": "KRW", "CN": "CNY"}.get(
        _normalize_country(country) or ""
    )
