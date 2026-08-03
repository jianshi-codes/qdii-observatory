"""Local provider configuration and neutral health states."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from backend.app.ingestion.http import ProviderHttpClient, RetryPolicy


class ProviderHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    SCHEMA_CHANGED = "SCHEMA_CHANGED"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


DEFAULT_USER_AGENT = "QDII-Observatory/0.1 (+local-first-research)"


class ProviderConfigurationError(RuntimeError):
    """Configured providers cannot support the requested operation."""


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    name: str
    enabled: bool = True
    priority: int = 100
    timeout_seconds: float = 20.0
    retry_attempts: int = 3
    rate_limit_per_second: float = 4.0
    user_agent: str = DEFAULT_USER_AGENT


DEFAULT_PROVIDERS_PATH = Path("config/providers.local.yaml")
EXAMPLE_PROVIDERS_PATH = Path("config/providers.example.yaml")


def load_provider_registry(path: Path | None = None) -> dict[str, ProviderConfig]:
    configured = path or Path(os.getenv("QDII_PROVIDERS_CONFIG", DEFAULT_PROVIDERS_PATH))
    source = configured if configured.is_file() else EXAMPLE_PROVIDERS_PATH
    if not source.is_file():
        return {}
    payload = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    raw_providers = payload.get("providers", payload)
    if not isinstance(raw_providers, dict):
        raise ValueError("provider config must contain a providers mapping")
    registry: dict[str, ProviderConfig] = {}
    for name, raw in raw_providers.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            raise ValueError("each provider entry must be a mapping keyed by name")
        registry[name] = _parse_provider(name, raw)
    return dict(sorted(registry.items(), key=lambda item: (item[1].priority, item[0])))


def _parse_provider(name: str, raw: dict[str, Any]) -> ProviderConfig:
    rate = float(raw.get("rate_limit_per_second", 4.0))
    timeout = float(raw.get("timeout_seconds", 20.0))
    attempts = int(raw.get("retry_attempts", 3))
    if rate <= 0 or timeout <= 0 or attempts < 1:
        raise ValueError(f"provider {name!r} has invalid timeout, retry, or rate limit")
    return ProviderConfig(
        name=name,
        enabled=bool(raw.get("enabled", True)),
        priority=int(raw.get("priority", 100)),
        timeout_seconds=timeout,
        retry_attempts=attempts,
        rate_limit_per_second=rate,
        user_agent=str(raw.get("user_agent", DEFAULT_USER_AGENT)),
    )


def provider_status(
    config: ProviderConfig,
    *,
    run_status: str | None = None,
    error_message: str | None = None,
) -> ProviderHealth:
    if not config.enabled:
        return ProviderHealth.DISABLED
    normalized_status = (run_status or "").strip().lower()
    if normalized_status == "succeeded":
        return ProviderHealth.HEALTHY
    if normalized_status == "partial":
        return ProviderHealth.DEGRADED
    if normalized_status == "failed":
        normalized_error = (error_message or "").lower()
        if any(token in normalized_error for token in ("429", "rate limit", "too many requests")):
            return ProviderHealth.RATE_LIMITED
        if any(
            token in normalized_error
            for token in ("schema", "unexpected payload", "missing required field")
        ):
            return ProviderHealth.SCHEMA_CHANGED
        return ProviderHealth.DEGRADED
    return ProviderHealth.UNKNOWN


def provider_client(*names: str) -> ProviderHttpClient:
    registry = load_provider_registry()
    selected = [registry[name] for name in names if name in registry]
    missing = [name for name in names if name not in registry]
    if missing:
        raise ProviderConfigurationError(f"providers are not configured: {missing}")
    disabled = [config.name for config in selected if not config.enabled]
    if disabled:
        raise ProviderConfigurationError(f"providers are disabled: {disabled}")
    if not selected:
        return ProviderHttpClient()
    return ProviderHttpClient(
        timeout_seconds=max(config.timeout_seconds for config in selected),
        min_interval_seconds=max(1 / config.rate_limit_per_second for config in selected),
        retry=RetryPolicy(attempts=max(config.retry_attempts for config in selected)),
        user_agent=selected[0].user_agent,
    )
