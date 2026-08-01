"""Import and validate a user-supplied QDII fund universe."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ingestion.ooxml import list_sheets, read_sheet
from backend.app.ingestion.runs import record_issue, resolve_issues
from backend.app.models import (
    ExposureFamily,
    FundContract,
    FundExposureFamily,
    FundShare,
    IngestionRun,
)

REQUESTED_SHEET = "基金合同明细"
SHEET_ALIASES = ("主基金明细", "Universe", "universe")
SHARE_SPLITTER = re.compile(r"[、,，;；\s]+")
FUND_CODE = re.compile(r"^[0-9]{6}$")
SHARE_CLASS = re.compile(r"(?:^|[^A-Z])([ACDEFIH])(?:类|份额|$|[（(])", re.IGNORECASE)
ALLOWED_CURRENCIES = frozenset({"CNY", "USD", "HKD"})
ALLOWED_WRAPPERS = frozenset({"DIRECT", "ETF", "ETF_FEEDER", "FOF", "LOF"})

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "representative_code": ("representative_code", "代表代码"),
    "representative_name": ("representative_name", "representative_fund_name", "代表基金名称"),
    "manager_name": ("manager_name", "基金公司", "基金管理人"),
    "canonical_name": ("canonical_name", "归并主基金名", "基金合同名称"),
    "share_codes": ("share_codes", "全部份额代码", "份额代码"),
    "share_names": ("share_names", "全部份额名称", "份额名称"),
    "share_currencies": ("share_currencies", "currencies", "currency", "份额币种", "币种"),
    "region": ("region", "主要区域"),
    "category": ("category", "领域分类"),
    "strategy_type": ("strategy_type", "策略类型"),
    "wrapper_type": ("wrapper_type", "产品包装"),
    "tech_scope": ("tech_scope", "科技范围"),
    "enabled": ("enabled", "启用"),
}
REQUIRED_FIELDS = (
    "representative_code",
    "representative_name",
    "manager_name",
    "canonical_name",
    "share_codes",
    "region",
    "category",
    "strategy_type",
)
EXPOSURE_FAMILY_DEFINITIONS = {
    "NASDAQ_100": ("纳斯达克 100", "主要暴露于 Nasdaq-100；不表示属于同一基金合同。"),
    "NASDAQ_TECH": ("纳斯达克科技", "主要暴露于纳斯达克科技主题指数。"),
    "GLOBAL_SEMICONDUCTOR": ("全球半导体", "主要暴露于全球半导体产业链。"),
    "CHINA_KOREA_SEMICONDUCTOR": ("中韩半导体", "主要暴露于中国与韩国半导体产业链。"),
    "GLOBAL_ACTIVE_EQUITY": ("全球主动权益", "主动选择全球权益资产。"),
    "GLOBAL_TECHNOLOGY_INTERNET": ("全球科技与互联网", "全球科技、互联网或数字经济暴露。"),
}


class UniverseValidationError(ValueError):
    """Validation error carrying structured diagnostics."""

    def __init__(self, message: str, diagnostics: dict[str, Any]):
        super().__init__(message)
        self.diagnostics = diagnostics


@dataclass(frozen=True, slots=True)
class ShareInput:
    code: str
    name: str | None
    share_class: str | None
    currency: str
    is_exchange_traded: bool
    exchange: str | None


@dataclass(frozen=True, slots=True)
class ContractInput:
    source_row: int
    representative_code: str
    representative_fund_name: str
    manager_name: str
    canonical_name: str
    declared_share_count: int
    shares: tuple[ShareInput, ...]
    region: str
    original_category: str
    strategy_type: str
    wrapper_type: str
    tech_scope: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class UniverseInput:
    workbook: Path
    requested_sheet: str
    actual_sheet: str
    sheet_alias_used: bool
    contracts: tuple[ContractInput, ...]

    @property
    def share_count(self) -> int:
        return sum(len(contract.shares) for contract in self.contracts)


def _normalize_code(raw: str) -> str:
    value = str(raw).strip()
    if re.fullmatch(r"[0-9]+(?:\.0+)?", value):
        value = value.split(".", maxsplit=1)[0]
    if not FUND_CODE.fullmatch(value):
        raise ValueError(f"fund code must contain exactly six digits, got {raw!r}")
    return value


def split_share_codes(raw: str) -> tuple[str, ...]:
    values = tuple(_normalize_code(item) for item in SHARE_SPLITTER.split(str(raw).strip()) if item)
    if not values:
        raise ValueError("share-code list is empty")
    return values


def _split_optional(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in SHARE_SPLITTER.split(str(raw).strip()) if item.strip())


def _wrapper_type(strategy_type: str, name: str) -> str:
    joined = f"{strategy_type} {name}".upper()
    if "ETF联接" in joined or "指数联接" in joined or "ETF FEEDER" in joined:
        return "ETF_FEEDER"
    if "FOF" in joined or "基金中基金" in joined:
        return "FOF"
    if re.search(r"(?:^|[^A-Z])ETF(?:[^A-Z]|$)", joined):
        return "ETF"
    if "LOF" in joined:
        return "LOF"
    return "DIRECT"


def _share_metadata(code: str, name: str | None, currency: str, wrapper: str) -> ShareInput:
    display_name = name or ""
    match = SHARE_CLASS.search(display_name)
    is_exchange_traded = wrapper in {"ETF", "LOF"} and code.startswith(("15", "16", "50", "51"))
    exchange = "SZSE" if is_exchange_traded and code.startswith(("15", "16")) else None
    if is_exchange_traded and code.startswith(("50", "51")):
        exchange = "SSE"
    return ShareInput(
        code=code,
        name=name,
        share_class=match.group(1).upper() if match else None,
        currency=currency,
        is_exchange_traded=is_exchange_traded,
        exchange=exchange,
    )


def _records_from_xlsx(path: Path) -> tuple[list[dict[str, Any]], str, bool]:
    sheets = list_sheets(path)
    actual_sheet = next(
        (name for name in (REQUESTED_SHEET, *SHEET_ALIASES) if name in sheets),
        sheets[0] if sheets else "",
    )
    if not actual_sheet:
        raise UniverseValidationError(
            "workbook contains no worksheets", {"available_sheets": sheets}
        )
    rows = read_sheet(path, actual_sheet)
    if not rows:
        raise UniverseValidationError("universe worksheet is empty", {"sheet": actual_sheet})
    headers = [value.strip() for value in rows[0]]
    records: list[dict[str, Any]] = []
    for row in rows[1:]:
        padded = row + [""] * max(0, len(headers) - len(row))
        records.append(dict(zip(headers, padded, strict=False)))
    return records, actual_sheet, actual_sheet != REQUESTED_SHEET


def _records_from_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _records_from_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("funds") if isinstance(payload, dict) else payload
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise UniverseValidationError("JSON universe must be an array or {funds: [...]}", {})
    return records


def _canonical_row(raw: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field, aliases in FIELD_ALIASES.items():
        value = next((raw.get(alias) for alias in aliases if raw.get(alias) not in (None, "")), "")
        if isinstance(value, list):
            result[field] = ",".join(str(item) for item in value)
        else:
            result[field] = str(value).strip()
    return result


def _enabled(value: str) -> bool:
    if not value:
        return True
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on", "是"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", "否"}:
        return False
    raise ValueError(f"enabled must be boolean, got {value!r}")


def load_universe(path: Path) -> UniverseInput:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        raw_records, actual_sheet, alias_used = _records_from_csv(path), "CSV", False
    elif suffix == ".json":
        raw_records, actual_sheet, alias_used = _records_from_json(path), "JSON", False
    elif suffix == ".xlsx":
        raw_records, actual_sheet, alias_used = _records_from_xlsx(path)
    else:
        raise UniverseValidationError(
            "universe file must be CSV, XLSX, or JSON", {"suffix": suffix}
        )

    contracts: list[ContractInput] = []
    errors: list[dict[str, Any]] = []
    for source_row, raw in enumerate(raw_records, start=2):
        row = _canonical_row(raw)
        missing = [field for field in REQUIRED_FIELDS if not row[field]]
        if missing:
            errors.append(
                {"source_row": source_row, "error": "empty_required_fields", "fields": missing}
            )
            continue
        try:
            representative = _normalize_code(row["representative_code"])
            codes = split_share_codes(row["share_codes"])
            if representative not in codes:
                raise ValueError("representative_code must be included in share_codes")
            names = _split_optional(row["share_names"])
            if names and len(names) != len(codes):
                raise ValueError("share_names must have the same item count as share_codes")
            currencies = tuple(item.upper() for item in _split_optional(row["share_currencies"]))
            if not currencies:
                currencies = tuple(
                    "USD" if names and "美元" in names[index] else "CNY"
                    for index in range(len(codes))
                )
            elif len(currencies) == 1:
                currencies = currencies * len(codes)
            if len(currencies) != len(codes):
                raise ValueError("share_currencies must contain one value or match share_codes")
            invalid_currencies = sorted(set(currencies) - ALLOWED_CURRENCIES)
            if invalid_currencies:
                raise ValueError(f"unsupported currencies: {invalid_currencies}")
            wrapper = (
                row["wrapper_type"]
                or _wrapper_type(row["strategy_type"], row["representative_name"])
            ).upper()
            if wrapper not in ALLOWED_WRAPPERS:
                raise ValueError(f"unsupported wrapper_type: {wrapper}")
            enabled = _enabled(row["enabled"])
        except ValueError as error:
            errors.append({"source_row": source_row, "error": str(error)})
            continue
        contracts.append(
            ContractInput(
                source_row=source_row,
                representative_code=representative,
                representative_fund_name=row["representative_name"],
                manager_name=row["manager_name"],
                canonical_name=row["canonical_name"],
                declared_share_count=len(codes),
                shares=tuple(
                    _share_metadata(
                        code, names[index] if names else None, currencies[index], wrapper
                    )
                    for index, code in enumerate(codes)
                ),
                region=row["region"],
                original_category=row["category"],
                strategy_type=row["strategy_type"],
                wrapper_type=wrapper,
                tech_scope=(row["tech_scope"] or "UNKNOWN").upper(),
                enabled=enabled,
            )
        )

    representative_codes = [item.representative_code for item in contracts]
    share_codes = [share.code for item in contracts for share in item.shares]
    canonical_names = [item.canonical_name.casefold() for item in contracts]
    duplicate_representatives = _duplicates(representative_codes)
    duplicate_shares = _duplicates(share_codes)
    duplicate_contracts = _duplicates(canonical_names)
    diagnostics = {
        "contract_count": len(contracts),
        "share_count": len(share_codes),
        "duplicate_representative_codes": duplicate_representatives,
        "duplicate_share_codes": duplicate_shares,
        "duplicate_contract_names": duplicate_contracts,
        "row_errors": errors,
    }
    if (
        not contracts
        or errors
        or duplicate_representatives
        or duplicate_shares
        or duplicate_contracts
    ):
        raise UniverseValidationError("QDII universe validation failed", diagnostics)
    return UniverseInput(
        workbook=path,
        requested_sheet=REQUESTED_SHEET if suffix == ".xlsx" else actual_sheet,
        actual_sheet=actual_sheet,
        sheet_alias_used=alias_used,
        contracts=tuple(contracts),
    )


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def import_universe(
    session: Session, universe: UniverseInput, run: IngestionRun
) -> tuple[int, int]:
    """Idempotently upsert contracts and shares, returning written counts."""

    contracts_written = 0
    shares_written = 0
    for item in universe.contracts:
        contract = session.scalar(
            select(FundContract).where(FundContract.representative_code == item.representative_code)
        )
        if contract is None:
            contract = FundContract(representative_code=item.representative_code)
            session.add(contract)
        contract.canonical_name = item.canonical_name
        contract.manager_name = item.manager_name
        contract.region = item.region
        contract.strategy_type = item.strategy_type
        contract.original_category = item.original_category
        contract.wrapper_type = item.wrapper_type
        contract.tech_scope = item.tech_scope
        contract.is_user_selected = item.enabled
        contract.is_dependency = False
        session.flush()
        contracts_written += 1

        _upsert_family_assignment(session, contract, item)
        for share_input in item.shares:
            share = session.scalar(
                select(FundShare).where(FundShare.share_code == share_input.code)
            )
            if share is None:
                share = FundShare(share_code=share_input.code)
                session.add(share)
            elif share.fund_contract_id != contract.id:
                raise UniverseValidationError(
                    "share code already belongs to another contract",
                    {"share_code": share_input.code, "incoming_contract_id": contract.id},
                )
            was_exchange_traded = share.is_exchange_traded
            share.fund_contract_id = contract.id
            share.share_class = share_input.share_class
            share.currency = share_input.currency
            share.is_exchange_traded = share_input.is_exchange_traded
            share.exchange = share_input.exchange
            if was_exchange_traded and not share_input.is_exchange_traded:
                resolve_issues(
                    session,
                    fund_contract_id=contract.id,
                    fund_share_id=share.id,
                    issue_codes=("MARKET_PRICE_SYNC_FAILED",),
                )
            shares_written += 1

    if universe.sheet_alias_used:
        record_issue(
            session,
            ingestion_run_id=run.id,
            issue_code="SOURCE_SHEET_ALIAS_USED",
            severity="WARNING",
            message=f"Used compatible worksheet {universe.actual_sheet!r}.",
            details={"actual_sheet": universe.actual_sheet, "source_file": universe.workbook.name},
        )
    session.flush()
    return contracts_written, shares_written


def _upsert_family_assignment(
    session: Session, contract: FundContract, item: ContractInput
) -> None:
    imported = list(
        session.scalars(
            select(FundExposureFamily).where(
                FundExposureFamily.fund_contract_id == contract.id,
                FundExposureFamily.fund_report_id.is_(None),
            )
        )
    )
    definition = EXPOSURE_FAMILY_DEFINITIONS.get(item.tech_scope)
    if definition is None:
        for stale in imported:
            session.delete(stale)
        return
    family = session.scalar(select(ExposureFamily).where(ExposureFamily.code == item.tech_scope))
    if family is None:
        family = ExposureFamily(code=item.tech_scope)
        session.add(family)
    family.display_name, family.description = definition
    session.flush()
    assignment = next((value for value in imported if value.exposure_family_id == family.id), None)
    for stale in imported:
        if stale is not assignment:
            session.delete(stale)
    if assignment is None:
        assignment = FundExposureFamily(
            fund_contract_id=contract.id, exposure_family_id=family.id, fund_report_id=None
        )
        session.add(assignment)
    assignment.confidence = Decimal("1.0")
    assignment.source_text = f"user universe tech_scope={item.tech_scope}"
