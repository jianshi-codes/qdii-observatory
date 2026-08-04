from __future__ import annotations

from collections.abc import Iterator

import pytest

from backend.app import config


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_portfolio_is_enabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QDII_ENABLE_PORTFOLIO", raising=False)
    monkeypatch.setattr(config, "load_dotenv", lambda *_args, **_kwargs: False)

    assert config.get_settings().portfolio_enabled is True


def test_portfolio_can_be_explicitly_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QDII_ENABLE_PORTFOLIO", "false")

    assert config.get_settings().portfolio_enabled is False
