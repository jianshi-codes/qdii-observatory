"""Storage configuration and fail-closed mount preflight."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024


class StoragePreflightError(RuntimeError):
    """Raised when a configured storage target is unsafe or unavailable."""


@dataclass(frozen=True, slots=True)
class StorageTarget:
    name: str
    path: Path
    explicitly_configured: bool
    external: bool
    free_bytes: int


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def configured_paths() -> tuple[tuple[str, Path, bool], ...]:
    root = repository_root()
    configured_pg = os.getenv("QDII_PG_DATA_SOURCE")
    configured_raw = os.getenv("QDII_RAW_DATA_DIR")
    paths: list[tuple[str, Path, bool]] = []
    if os.getenv("QDII_PG_VOLUME_TYPE", "volume").strip().lower() == "bind":
        if not configured_pg:
            raise StoragePreflightError(
                "QDII_PG_DATA_SOURCE is required when QDII_PG_VOLUME_TYPE=bind"
            )
        paths.append(
            (
                "QDII_PG_DATA_SOURCE",
                Path(configured_pg).expanduser(),
                True,
            )
        )
    paths.append(
        (
            "QDII_RAW_DATA_DIR",
            Path(configured_raw).expanduser() if configured_raw else root / ".data" / "raw",
            configured_raw is not None,
        )
    )
    return tuple(paths)


def _check_writable(path: Path) -> None:
    try:
        descriptor, probe = tempfile.mkstemp(prefix=".qdii-preflight-", dir=path)
        os.close(descriptor)
        Path(probe).unlink()
    except OSError as error:
        raise StoragePreflightError(
            f"Storage directory is not writable: {path}: {error}"
        ) from error


def storage_preflight(min_free_bytes: int | None = None) -> tuple[StorageTarget, ...]:
    """Validate local defaults or explicit external targets without fallback.

    Named Docker volumes are managed by Compose and are not inspected here.
    An explicitly selected PostgreSQL bind mount and the raw-artifact directory
    are validated without falling back to a different location.
    """

    root = repository_root().resolve()
    configured_managed_root = os.getenv("QDII_MANAGED_DATA_ROOT")
    managed_root = None
    if configured_managed_root:
        candidate = Path(configured_managed_root).expanduser()
        managed_root = (candidate if candidate.is_absolute() else root / candidate).resolve()
        if not managed_root.is_dir():
            raise StoragePreflightError(
                f"QDII_MANAGED_DATA_ROOT is not an existing directory: {managed_root}"
            )
    minimum = min_free_bytes
    if minimum is None:
        minimum = int(os.getenv("QDII_MIN_FREE_BYTES", str(DEFAULT_MIN_FREE_BYTES)))
    results: list[StorageTarget] = []
    for name, configured, explicit in configured_paths():
        path = configured if configured.is_absolute() else root / configured
        path = path.resolve()
        external = not _inside(path, root)
        managed = managed_root is not None and _inside(path, managed_root)
        if not path.exists():
            if external and not managed:
                raise StoragePreflightError(
                    f"{name} does not exist: {path}. External paths are never auto-created."
                )
            path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            raise StoragePreflightError(f"{name} is not a directory: {path}")
        if external and not managed and path.stat().st_dev == Path(path.anchor).stat().st_dev:
            raise StoragePreflightError(
                f"{name} appears to be on the system filesystem, not a mounted "
                f"external volume: {path}"
            )
        _check_writable(path)
        free_bytes = shutil.disk_usage(path).free
        if free_bytes < minimum:
            raise StoragePreflightError(
                f"{name} has insufficient free space: {free_bytes} bytes; "
                f"required {minimum}: {path}"
            )
        results.append(
            StorageTarget(
                name=name,
                path=path,
                explicitly_configured=explicit,
                external=external,
                free_bytes=free_bytes,
            )
        )
    return tuple(results)


def raw_data_dir() -> Path:
    return next(target.path for target in storage_preflight() if target.name == "QDII_RAW_DATA_DIR")
