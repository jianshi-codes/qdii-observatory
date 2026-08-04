"""Local initialization, diagnostics, backup, and restore helpers."""

from __future__ import annotations

import shutil
import socket
import subprocess
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import Settings
from backend.app.database import SessionLocal, engine
from backend.app.ingestion.provider_registry import load_provider_registry, provider_status
from backend.app.models import DailyFundNav, FundContract, FundReport


@dataclass(frozen=True, slots=True)
class InitResult:
    created: tuple[str, ...]
    preserved: tuple[str, ...]


def initialize_project(root: Path) -> InitResult:
    created: list[str] = []
    preserved: list[str] = []
    env_target = root / ".env"
    _copy_if_absent(root / ".env.example", env_target, root, created, preserved)
    for data_dir in (root / ".data" / "private", root / ".data" / "raw"):
        if data_dir.exists():
            preserved.append(str(data_dir.relative_to(root)))
        else:
            data_dir.mkdir(parents=True)
            created.append(str(data_dir.relative_to(root)))
    overrides = {
        root / "config" / "fund-analysis-proxies.local.yaml": (
            "version: 1\nalignment_overrides: {}\nfunds: {}\nconsistency_rules: {}\n"
        ),
        root / "config" / "analysis-security-map.local.yaml": (
            "version: 1\nmappings: []\n"
        ),
        root / "config" / "local.yaml": "{}\n",
    }
    for path, content in overrides.items():
        if path.exists():
            preserved.append(str(path.relative_to(root)))
        else:
            path.write_text(content, encoding="utf-8")
            created.append(str(path.relative_to(root)))
    return InitResult(tuple(created), tuple(preserved))


def _copy_if_absent(
    source: Path, target: Path, root: Path, created: list[str], preserved: list[str]
) -> None:
    relative = str(target.relative_to(root))
    if target.exists():
        preserved.append(relative)
        return
    shutil.copyfile(source, target)
    created.append(relative)


def doctor(settings: Settings, *, check_network: bool = True) -> dict[str, object]:
    checks: dict[str, object] = {
        "configuration": "OK" if settings.database_url else "ERROR",
        "portfolio_enabled": settings.portfolio_enabled,
    }
    data_dir = Path(".data")
    checks["data_directory"] = (
        "OK" if data_dir.is_dir() and _is_writable(data_dir) else "MISSING_OR_NOT_WRITABLE"
    )
    providers = load_provider_registry()
    checks["providers"] = {
        name: provider_status(config).value for name, config in providers.items()
    }
    checks["network_reachability"] = (
        _provider_network_checks(providers) if check_network else "SKIPPED"
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            checks["postgresql"] = "OK" if engine.dialect.name == "postgresql" else "NOT_CONFIGURED"
            try:
                checks["migration"] = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
            except SQLAlchemyError:
                checks["migration"] = "MISSING"
    except SQLAlchemyError as error:
        checks["database"] = f"ERROR:{type(error).__name__}"
        checks["migration"] = "UNKNOWN"
        return checks
    with SessionLocal() as session:
        checks["universe_contracts"] = (
            session.scalar(select(func.count()).select_from(FundContract)) or 0
        )
        checks["latest_report"] = session.scalar(select(func.max(FundReport.period_end)))
        checks["latest_nav"] = session.scalar(select(func.max(DailyFundNav.nav_date)))
    checks["cache_permissions"] = checks["data_directory"]
    return checks


def _is_writable(path: Path) -> bool:
    return path.stat().st_mode & 0o200 != 0


def _provider_network_checks(providers: Mapping[str, object]) -> dict[str, str]:
    hosts = {
        "csrc_reports": "eid.csrc.gov.cn",
        "eastmoney_nav": "fundf10.eastmoney.com",
        "eastmoney_market": "push2his.eastmoney.com",
        "ecb_fx": "www.ecb.europa.eu",
    }
    results: dict[str, str] = {}
    for name, config in providers.items():
        if not getattr(config, "enabled", False):
            results[name] = "DISABLED"
            continue
        host = hosts.get(name)
        if host is None:
            results[name] = "UNKNOWN"
            continue
        try:
            socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            results[name] = "REACHABLE"
        except OSError:
            results[name] = "UNREACHABLE"
    return results


def backup_database(settings: Settings, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if settings.database_url.startswith("sqlite"):
        database = make_url(settings.database_url).database
        if database is None:
            raise ValueError("SQLite database URL has no file path")
        source = Path(database)
        target = output_dir / f"qdii-observatory-{timestamp}.sqlite"
        shutil.copy2(source, target)
        return target
    target = output_dir / f"qdii-observatory-{timestamp}.dump"
    database_url = str(make_url(settings.database_url).set(drivername="postgresql"))
    subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(target), database_url],
        check=True,
    )
    return target


def restore_database(settings: Settings, backup_file: Path, *, confirmed: bool) -> None:
    if not confirmed:
        raise ValueError("restore requires --confirm")
    if not backup_file.is_file():
        raise FileNotFoundError(backup_file)
    if settings.database_url.startswith("sqlite"):
        database = make_url(settings.database_url).database
        if database is None:
            raise ValueError("SQLite database URL has no file path")
        target = Path(database)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_file, target)
        return
    database_url = str(make_url(settings.database_url).set(drivername="postgresql"))
    subprocess.run(
        ["pg_restore", "--clean", "--if-exists", "--dbname", database_url, str(backup_file)],
        check=True,
    )


def init_payload(result: InitResult) -> dict[str, object]:
    return asdict(result)
