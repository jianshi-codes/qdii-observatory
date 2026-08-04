from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from backend.app.q2_analysis import predictor, security_mapping


@pytest.fixture(autouse=True)
def clear_config_caches() -> Iterator[None]:
    predictor._load_proxy_document.cache_clear()
    security_mapping.load_manual_mappings.cache_clear()
    yield
    predictor._load_proxy_document.cache_clear()
    security_mapping.load_manual_mappings.cache_clear()


def test_public_proxy_config_contains_rules_but_no_personal_funds() -> None:
    assert predictor.load_proxy_config("123456", predictor.PUBLIC_PROXY_PATH) is None
    assert predictor.load_consistency_rule_values(predictor.PUBLIC_PROXY_PATH)[
        "minimum_observations"
    ] == 5


def test_local_proxy_config_merges_over_public_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public = tmp_path / "public.yaml"
    public.write_text(
        "version: 1\n"
        "alignment_overrides: {}\n"
        "funds: {}\n"
        "consistency_rules:\n"
        "  minimum_observations: 5\n",
        encoding="utf-8",
    )
    local = tmp_path / "local.yaml"
    local.write_text(
        "version: 1\n"
        "funds:\n"
        '  "123456":\n'
        "    proxies:\n"
        "      - symbol: EXAMPLE\n"
        "        currency: USD\n"
        "        weight: 1\n"
        "    reason: synthetic local override\n"
        "    confidence: LOW\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(predictor, "PUBLIC_PROXY_PATH", public)
    monkeypatch.setattr(predictor, "LOCAL_PROXY_PATH", local)

    config = predictor.load_proxy_config("123456")

    assert config is not None
    assert config.proxies[0].weight == Decimal("1")
    assert predictor.load_consistency_rule_values()["minimum_observations"] == 5


def test_local_security_mapping_takes_priority_over_public_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    public = tmp_path / "public.yaml"
    public.write_text(
        "version: 1\n"
        "mappings:\n"
        "  - match: {security_code_raw: EXAMPLE-US, market: US}\n"
        "    symbol: PUBLIC\n"
        "    currency: USD\n"
        "    reason: public mapping\n",
        encoding="utf-8",
    )
    local = tmp_path / "local.yaml"
    local.write_text(
        "version: 1\n"
        "mappings:\n"
        "  - match: {security_code_raw: EXAMPLE-US, market: US}\n"
        "    symbol: LOCAL\n"
        "    currency: USD\n"
        "    reason: local override\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(security_mapping, "PUBLIC_MAPPING_PATH", public)
    monkeypatch.setattr(security_mapping, "LOCAL_MAPPING_PATH", local)

    mappings = security_mapping.load_manual_mappings()

    assert len(mappings) == 1
    assert mappings[0].symbol == "LOCAL"
