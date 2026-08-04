"""Parse and preview the local-only Portfolio XLSX workbook."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ingestion.ooxml import WorkbookFormatError, list_sheets, read_sheet
from backend.app.ingestion.providers.base import FundCatalogProvider
from backend.app.models import DailyFundNav, FundShare, PortfolioPosition

MAX_PORTFOLIO_FILE_BYTES = 2 * 1024 * 1024
MAX_POSITION_ROWS = 200
MAX_CASH_FLOW_ROWS = 1000
FUND_CODE = re.compile(r"^[0-9]{6}$")
EXCEL_EPOCH = date(1899, 12, 30)

POSITION_FIELDS: dict[str, tuple[str, ...]] = {
    "share_code": ("基金代码", "share_code"),
    "platform": ("平台", "platform"),
    "snapshot_date": ("快照日期", "snapshot_date"),
    "currency": ("币种", "currency"),
    "units": ("持有份额", "份额", "units"),
    "market_value": ("当前市值", "market_value"),
    "holding_profit": ("持有收益", "holding_profit"),
    "holding_return_pct": ("持有收益率", "holding_return_pct"),
    "cumulative_profit": ("累计收益", "cumulative_profit"),
    "recurring_gross_amount": ("每日定投金额", "recurring_gross_amount"),
    "recurring_fee_pct": ("定投费率", "recurring_fee_pct"),
    "purchase_fee_pct": ("申购费率", "purchase_fee_pct"),
    "management_fee_pct_annual": ("管理费率（年）", "management_fee_pct_annual"),
    "custody_fee_pct_annual": ("托管费率（年）", "custody_fee_pct_annual"),
    "active": ("启用", "active"),
}
CASH_FLOW_FIELDS: dict[str, tuple[str, ...]] = {
    "share_code": ("基金代码", "share_code"),
    "platform": ("平台", "platform"),
    "occurred_on": ("日期", "occurred_on"),
    "occurred_year": ("年份", "occurred_year"),
    "amount": ("分红金额", "amount"),
    "currency": ("币种", "currency"),
    "note": ("备注", "note"),
}


@dataclass(frozen=True, slots=True)
class PortfolioWorkbook:
    file_digest: str
    payload: dict[str, list[dict[str, Any]]]
    position_rows: dict[tuple[str, str], int]
    errors: tuple[dict[str, Any], ...]


def parse_portfolio_workbook(content: bytes) -> PortfolioWorkbook:
    if not content:
        raise ValueError("上传文件为空")
    if len(content) > MAX_PORTFOLIO_FILE_BYTES:
        raise ValueError("XLSX 文件不能超过 2 MB")
    try:
        sheets = list_sheets(BytesIO(content))
    except (BadZipFile, WorkbookFormatError, OSError) as error:
        raise ValueError(f"无法读取 XLSX：{error}") from error
    if "持仓" not in sheets:
        raise ValueError("XLSX 缺少“持仓”工作表")

    errors: list[dict[str, Any]] = []
    try:
        positions, position_rows = _parse_positions(content, errors)
        flows = _parse_cash_flows(content, sheets, position_rows, errors)
    except (BadZipFile, WorkbookFormatError, OSError, ParseError) as error:
        raise ValueError(f"无法读取 XLSX：{error}") from error
    flows_by_identity: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for flow in flows:
        identity = (flow.pop("_platform"), flow.pop("_share_code"))
        flows_by_identity.setdefault(identity, []).append(flow)
    for position in positions:
        identity = (str(position["platform"]), str(position["share_code"]))
        if identity in flows_by_identity:
            position["cash_flows"] = flows_by_identity[identity]

    if not positions and not errors:
        errors.append(_error("持仓", 5, "NO_POSITIONS", "至少填写一行持仓"))
    return PortfolioWorkbook(
        file_digest=hashlib.sha256(content).hexdigest(),
        payload={"positions": positions},
        position_rows=position_rows,
        errors=tuple(errors),
    )


def build_portfolio_preview(
    session: Session,
    workbook: PortfolioWorkbook,
    provider: FundCatalogProvider,
) -> dict[str, Any]:
    errors = list(workbook.errors)
    items: list[dict[str, Any]] = []
    lookup_cache: dict[str, Any] = {}
    for raw in workbook.payload["positions"]:
        code = str(raw["share_code"])
        platform = str(raw["platform"])
        row = workbook.position_rows[(platform, code)]
        share = session.scalar(select(FundShare).where(FundShare.share_code == code))
        if share is None:
            try:
                if code not in lookup_cache:
                    lookup_cache[code] = provider.lookup(code).candidates[0]
                candidate = lookup_cache[code]
            except Exception as error:
                errors.append(
                    _error(
                        "持仓",
                        row,
                        "PUBLIC_FUND_LOOKUP_FAILED",
                        f"基金 {code} 无法从公开目录确认：{error}",
                    )
                )
                continue
            expected_currency = candidate.currency
            fund_name = candidate.fund_name
            manager_name = candidate.manager_name
            universe_action = "ADD"
            nav_ready = False
        else:
            contract = share.fund_contract
            expected_currency = share.currency
            fund_name = contract.canonical_name
            manager_name = contract.manager_name
            universe_action = "KEEP" if contract.is_user_selected else "RESTORE"
            nav_ready = _anchor_nav(session, share.id, raw["snapshot_date"]) is not None

        supplied_currency = str(raw.get("currency") or "").upper()
        if supplied_currency and supplied_currency != expected_currency:
            errors.append(
                _error(
                    "持仓",
                    row,
                    "CURRENCY_MISMATCH",
                    f"基金 {code} 币种应为 {expected_currency}，模板填写为 {supplied_currency}",
                )
            )
        existing_position = (
            session.scalar(
                select(PortfolioPosition).where(
                    PortfolioPosition.platform == platform,
                    PortfolioPosition.fund_share_id == share.id,
                )
            )
            if share is not None
            else None
        )
        items.append(
            {
                "source_row": row,
                "share_code": code,
                "fund_name": fund_name,
                "manager_name": manager_name,
                "platform": platform,
                "snapshot_date": raw["snapshot_date"],
                "currency": supplied_currency or expected_currency,
                "units": raw["units"],
                "market_value": raw["market_value"],
                "holding_profit": raw["holding_profit"],
                "holding_return_pct": raw["holding_return_pct"],
                "position_action": "UPDATE" if existing_position is not None else "ADD",
                "universe_action": universe_action,
                "nav_action": "KEEP" if nav_ready else "SYNC",
            }
        )
    return {
        "file_digest": workbook.file_digest,
        "valid": not errors,
        "positions": items,
        "errors": errors,
        "summary": {
            "position_count": len(workbook.payload["positions"]),
            "cash_flow_count": sum(
                len(item.get("cash_flows", [])) for item in workbook.payload["positions"]
            ),
            "positions_to_add": sum(item["position_action"] == "ADD" for item in items),
            "positions_to_update": sum(item["position_action"] == "UPDATE" for item in items),
            "universe_to_add": sum(item["universe_action"] == "ADD" for item in items),
            "universe_to_restore": sum(item["universe_action"] == "RESTORE" for item in items),
            "nav_to_sync": sum(item["nav_action"] == "SYNC" for item in items),
        },
    }


def anchor_missing_codes(session: Session, workbook: PortfolioWorkbook) -> set[str]:
    missing: set[str] = set()
    for raw in workbook.payload["positions"]:
        share = session.scalar(
            select(FundShare).where(FundShare.share_code == str(raw["share_code"]))
        )
        if share is None or _anchor_nav(session, share.id, raw["snapshot_date"]) is None:
            missing.add(str(raw["share_code"]))
    return missing


def nav_sync_range(workbook: PortfolioWorkbook) -> tuple[date, date]:
    snapshot_dates = [item["snapshot_date"] for item in workbook.payload["positions"]]
    return min(snapshot_dates) - timedelta(days=60), max(snapshot_dates)


def _parse_positions(
    content: bytes,
    errors: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], int]]:
    rows = read_sheet(BytesIO(content), "持仓")
    header_index, headers = _header(
        rows,
        POSITION_FIELDS,
        required=("share_code", "platform", "units"),
    )
    positions: list[dict[str, Any]] = []
    position_rows: dict[tuple[str, str], int] = {}
    for index, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        raw = _row(row, headers)
        if not any(raw.values()):
            continue
        if len(positions) >= MAX_POSITION_ROWS:
            errors.append(_error("持仓", index, "TOO_MANY_POSITIONS", "持仓最多 200 行"))
            break
        try:
            position = _position(raw)
            identity = (str(position["platform"]), str(position["share_code"]))
            if identity in position_rows:
                raise ValueError(
                    f"平台与基金代码重复，首次出现在第 {position_rows[identity]} 行"
                )
            position_rows[identity] = index
            positions.append(position)
        except ValueError as error:
            errors.append(_error("持仓", index, "INVALID_POSITION", str(error)))
    return positions, position_rows


def _parse_cash_flows(
    content: bytes,
    sheets: list[str],
    position_rows: dict[tuple[str, str], int],
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if "现金流" not in sheets:
        return []
    rows = read_sheet(BytesIO(content), "现金流")
    header_index, headers = _header(rows, CASH_FLOW_FIELDS, required=("share_code", "platform"))
    flows: list[dict[str, Any]] = []
    for index, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        raw = _row(row, headers)
        if not any(raw.values()):
            continue
        if len(flows) >= MAX_CASH_FLOW_ROWS:
            errors.append(_error("现金流", index, "TOO_MANY_CASH_FLOWS", "现金流最多 1000 行"))
            break
        try:
            flow = _cash_flow(raw)
            identity = (str(flow["_platform"]), str(flow["_share_code"]))
            if identity not in position_rows:
                raise ValueError("基金代码与平台必须先出现在“持仓”工作表")
            flows.append(flow)
        except ValueError as error:
            errors.append(_error("现金流", index, "INVALID_CASH_FLOW", str(error)))
    return flows


def _position(raw: dict[str, str]) -> dict[str, Any]:
    share_code = _code(raw.get("share_code"))
    platform = _required(raw.get("platform"), "平台")
    snapshot_date = _date(raw.get("snapshot_date"), "快照日期")
    if snapshot_date > date.today():
        raise ValueError("快照日期不能晚于今天")
    units = _decimal(raw.get("units"), "持有份额", positive=True)
    market_value = _decimal(raw.get("market_value"), "当前市值", positive=True)
    holding_profit = _decimal(raw.get("holding_profit"), "持有收益")
    holding_return = _percent(raw.get("holding_return_pct"), "持有收益率", required=True)
    currency = (raw.get("currency") or "").strip().upper()
    if currency and currency not in {"CNY", "USD", "HKD"}:
        raise ValueError(f"不支持的币种：{currency}")
    result: dict[str, Any] = {
        "share_code": share_code,
        "platform": platform,
        "snapshot_date": snapshot_date,
        "currency": currency or None,
        "units": str(units),
        "market_value": str(market_value),
        "holding_profit": str(holding_profit),
        "holding_return_pct": str(holding_return),
        "active": _boolean(raw.get("active")),
    }
    for key, label in (
        ("cumulative_profit", "累计收益"),
        ("recurring_gross_amount", "每日定投金额"),
    ):
        value = _optional_decimal(raw.get(key), label, positive=key == "recurring_gross_amount")
        if value is not None:
            result[key] = str(value)
    for key, label in (
        ("recurring_fee_pct", "定投费率"),
        ("purchase_fee_pct", "申购费率"),
        ("management_fee_pct_annual", "管理费率（年）"),
        ("custody_fee_pct_annual", "托管费率（年）"),
    ):
        value = _percent(raw.get(key), label, required=False)
        if value is not None:
            result[key] = str(value)
    if "recurring_gross_amount" in result:
        result["recurring_plan"] = {
            "gross_amount": result.pop("recurring_gross_amount"),
            "fee_pct": result.pop("recurring_fee_pct", "0"),
        }
    elif "recurring_fee_pct" in result:
        raise ValueError("填写定投费率时必须同时填写每日定投金额")
    return result


def _cash_flow(raw: dict[str, str]) -> dict[str, Any]:
    share_code = _code(raw.get("share_code"))
    platform = _required(raw.get("platform"), "平台")
    occurred_on = _optional_date(raw.get("occurred_on"), "日期")
    year_text = (raw.get("occurred_year") or "").strip()
    try:
        occurred_year = (
            int(Decimal(year_text)) if year_text else occurred_on.year if occurred_on else 0
        )
    except (InvalidOperation, ValueError) as error:
        raise ValueError("年份必须是四位数字") from error
    if not 2000 <= occurred_year <= 2100:
        raise ValueError("现金流必须填写日期或 2000–2100 年之间的年份")
    currency = (raw.get("currency") or "").strip().upper()
    if currency and currency not in {"CNY", "USD", "HKD"}:
        raise ValueError(f"不支持的币种：{currency}")
    result: dict[str, Any] = {
        "_share_code": share_code,
        "_platform": platform,
        "occurred_year": occurred_year,
        "amount": str(_decimal(raw.get("amount"), "分红金额", positive=True)),
    }
    if occurred_on is not None:
        result["occurred_on"] = occurred_on
    if currency:
        result["currency"] = currency
    note = (raw.get("note") or "").strip()
    if note:
        result["note"] = note
    return result


def _header(
    rows: list[list[str]],
    fields: dict[str, tuple[str, ...]],
    *,
    required: tuple[str, ...],
) -> tuple[int, dict[int, str]]:
    aliases = {alias: key for key, values in fields.items() for alias in values}
    for index, row in enumerate(rows[:10]):
        mapped = {
            column: aliases[value.strip()]
            for column, value in enumerate(row)
            if value.strip() in aliases
        }
        if all(field in mapped.values() for field in required):
            return index, mapped
    raise ValueError(f"工作表缺少必要表头：{list(required)}")


def _row(row: list[str], headers: dict[int, str]) -> dict[str, str]:
    return {
        field: (row[index].strip() if index < len(row) else "")
        for index, field in headers.items()
    }


def _anchor_nav(session: Session, share_id: int, snapshot_date: date) -> DailyFundNav | None:
    return session.scalar(
        select(DailyFundNav)
        .where(DailyFundNav.fund_share_id == share_id, DailyFundNav.nav_date <= snapshot_date)
        .order_by(DailyFundNav.nav_date.desc(), DailyFundNav.id.desc())
        .limit(1)
    )


def _code(value: str | None) -> str:
    text = (value or "").strip()
    if re.fullmatch(r"[0-9]+(?:\.0+)?", text):
        text = text.split(".", maxsplit=1)[0].zfill(6)
    if not FUND_CODE.fullmatch(text):
        raise ValueError("基金代码必须是六位数字")
    return text


def _required(value: str | None, label: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"{label}不能为空")
    return text


def _date(value: str | None, label: str) -> date:
    parsed = _optional_date(value, label)
    if parsed is None:
        raise ValueError(f"{label}不能为空")
    return parsed


def _optional_date(value: str | None, label: str) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        if re.fullmatch(r"[0-9]+(?:\.0+)?", text):
            serial = int(Decimal(text))
            if 20000 <= serial <= 80000:
                return EXCEL_EPOCH + timedelta(days=serial)
        return date.fromisoformat(text)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label}必须是 yyyy-mm-dd 日期") from error


def _decimal(value: str | None, label: str, *, positive: bool = False) -> Decimal:
    text = (value or "").replace(",", "").strip()
    if not text:
        raise ValueError(f"{label}不能为空")
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"{label}必须是数字") from error
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError(f"{label}必须是正数" if positive else f"{label}不是有效数字")
    return number


def _optional_decimal(
    value: str | None,
    label: str,
    *,
    positive: bool = False,
) -> Decimal | None:
    if not (value or "").strip():
        return None
    return _decimal(value, label, positive=positive)


def _percent(value: str | None, label: str, *, required: bool) -> Decimal | None:
    text = (value or "").strip()
    if not text:
        if required:
            raise ValueError(f"{label}不能为空")
        return None
    has_symbol = text.endswith("%")
    number = _decimal(text.removesuffix("%"), label)
    percent = number if has_symbol else number * Decimal("100")
    if not Decimal("-1000") <= percent <= Decimal("1000"):
        raise ValueError(f"{label}超出可接受范围")
    if label != "持有收益率" and not Decimal("0") <= percent <= Decimal("100"):
        raise ValueError(f"{label}必须在 0%–100% 之间")
    return percent


def _boolean(value: str | None) -> bool:
    text = (value or "").strip().lower()
    if not text or text in {"是", "true", "1", "yes", "on"}:
        return True
    if text in {"否", "false", "0", "no", "off"}:
        return False
    raise ValueError("启用只能填写“是”或“否”")


def _error(sheet: str, row: int, code: str, message: str) -> dict[str, Any]:
    return {"sheet": sheet, "row": row, "code": code, "message": message}
