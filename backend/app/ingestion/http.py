"""Bounded HTTP transport shared by external providers."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

DEFAULT_USER_AGENT = "QDII-Observatory/0.1 (+local-first-research)"


class ProviderHttpError(RuntimeError):
    """HTTP failure retaining status and URL without swallowing the provider attempt."""

    def __init__(self, message: str, *, url: str, status_code: int | None = None):
        super().__init__(message)
        self.url = url
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0


class ProviderHttpClient:
    """Synchronous, rate-limited client for CLI ingestion jobs."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        min_interval_seconds: float = 0.25,
        retry: RetryPolicy | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "*/*"},
            transport=transport,
        )
        self._min_interval = min_interval_seconds
        self._retry = retry or RetryPolicy()
        self._last_request_at = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ProviderHttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self._retry.attempts):
            remaining = self._min_interval - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
            try:
                response = self._client.request(method, url, **kwargs)
                self._last_request_at = time.monotonic()
                if response.status_code < 400:
                    return response
                if response.status_code not in {408, 425, 429, 500, 502, 503, 504}:
                    raise ProviderHttpError(
                        f"Provider returned HTTP {response.status_code}",
                        url=str(response.url),
                        status_code=response.status_code,
                    )
                last_error = ProviderHttpError(
                    f"Retryable provider HTTP {response.status_code}",
                    url=str(response.url),
                    status_code=response.status_code,
                )
                retry_after = _retry_after_seconds(response)
            except (httpx.TimeoutException, httpx.TransportError) as error:
                self._last_request_at = time.monotonic()
                last_error = error
                retry_after = None
            if attempt + 1 < self._retry.attempts:
                exponential = min(
                    self._retry.max_delay_seconds,
                    self._retry.base_delay_seconds * 2**attempt,
                )
                time.sleep(retry_after or exponential + random.uniform(0, exponential / 4))
        if isinstance(last_error, ProviderHttpError):
            raise last_error
        raise ProviderHttpError(
            f"Provider request failed after {self._retry.attempts} attempts: {last_error}",
            url=url,
        ) from last_error


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError):
            return None
