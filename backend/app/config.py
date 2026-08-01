"""Small, environment-driven application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_DATABASE_URL = "sqlite+pysqlite:///./.data/qdii-observatory.db"
DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _boolean_env(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    api_prefix: str = "/api"
    portfolio_enabled: bool = False
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(REPOSITORY_ROOT / ".env", override=False)
    database_url = (
        os.getenv("QDII_DATABASE_URL") or os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL
    )
    configured_origins = os.getenv("QDII_CORS_ORIGINS", "")
    cors_origins = tuple(
        origin.strip().rstrip("/") for origin in configured_origins.split(",") if origin.strip()
    )
    return Settings(
        database_url=database_url,
        portfolio_enabled=_boolean_env("QDII_ENABLE_PORTFOLIO"),
        cors_origins=cors_origins or DEFAULT_CORS_ORIGINS,
    )
