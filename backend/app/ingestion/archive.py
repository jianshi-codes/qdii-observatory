"""Content-addressed raw response archival outside PostgreSQL."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class ArchivedArtifact:
    path: Path
    sha256: str
    byte_size: int
    fetched_at: datetime


def safe_segment(value: str) -> str:
    segment = SAFE_SEGMENT.sub("-", value.strip()).strip(".-")
    if not segment:
        raise ValueError("Archive path segment is empty")
    return segment


def archive_bytes(
    root: Path,
    relative_directory: Path,
    filename_stem: str,
    suffix: str,
    payload: bytes,
) -> ArchivedArtifact:
    """Write a response atomically; identical content resolves to one immutable name."""

    digest = hashlib.sha256(payload).hexdigest()
    directory = (root / relative_directory).resolve()
    root_resolved = root.resolve()
    try:
        directory.relative_to(root_resolved)
    except ValueError as error:
        raise ValueError("Archive path escaped QDII_RAW_DATA_DIR") from error
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{safe_segment(filename_stem)}-{digest[:16]}{suffix}"
    if not target.exists():
        descriptor, temporary_name = tempfile.mkstemp(prefix=".qdii-write-", dir=directory)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, target)
        finally:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()
    return ArchivedArtifact(
        path=target,
        sha256=digest,
        byte_size=len(payload),
        fetched_at=datetime.now(UTC),
    )
