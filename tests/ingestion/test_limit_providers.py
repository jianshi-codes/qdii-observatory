from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest

from backend.app.ingestion.providers import limits
from backend.app.ingestion.providers.base import ProviderSchemaError, PurchaseLimitRecord


@pytest.fixture(autouse=True)
def empty_csrc_pdf_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(limits, "_extract_pdf_tables", lambda _: (), raising=False)


class FixtureEastmoneyLimitHttp:
    def __init__(self, html: str) -> None:
        self.html = html
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **_: Any) -> httpx.Response:
        self.calls.append((method, url))
        return httpx.Response(
            200,
            text=self.html,
            headers={"content-type": "text/html; charset=utf-8"},
            request=httpx.Request(method, url),
        )


class FixtureCsrcLimitHttp:
    def __init__(self, fund_id: int, detail_html: str) -> None:
        self.fund_id = fund_id
        self.detail_html = detail_html
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **_: Any) -> httpx.Response:
        self.calls.append((method, url))
        request = httpx.Request(method, url)
        if url.endswith("validate_fund.do"):
            return httpx.Response(
                200,
                content=json.dumps({"isSuccess": True, "fundId": self.fund_id}).encode(),
                headers={"content-type": "application/json"},
                request=request,
            )
        if "fund_detail_search.do" in url:
            return httpx.Response(
                200,
                text=self.detail_html,
                headers={"content-type": "text/html; charset=utf-8"},
                request=request,
            )
        if "instance_show_pdf_id.do" in url:
            return httpx.Response(
                200,
                content=b"%PDF-fixture",
                headers={"content-type": "application/pdf"},
                request=request,
            )
        raise AssertionError(f"Unexpected fixture request: {method} {url}")


def _eastmoney_html(share_code: str, body: str) -> str:
    return f"""
    <html><head><title>测试基金({share_code})</title></head>
    <body><h1>测试基金({share_code})</h1><table>{body}</table></body></html>
    """


def _csrc_detail_html(*, instance_id: int, published_on: str, title: str) -> str:
    return f"""
    <html><body><table><tr>
      <td>{published_on}</td>
      <td><a href="instance_show_pdf_id.do?instanceid={instance_id}">{title}</a></td>
    </tr></table></body></html>
    """


def _record_by_channel(
    records: Sequence[PurchaseLimitRecord],
    share_code: str,
    channel_key: str,
    business_type: str = "PURCHASE",
) -> PurchaseLimitRecord:
    return next(
        record
        for record in records
        if record.share_code == share_code
        and record.channel_key == channel_key
        and record.business_type == business_type
    )


def test_eastmoney_limit_is_named_distributor_only() -> None:
    http = FixtureEastmoneyLimitHttp(
        _eastmoney_html(
            "000834",
            """
            <tr><th>申购状态</th><td>限大额</td></tr>
            <tr><th>日累计申购限额</th><td>10元</td></tr>
            """,
        )
    )
    provider = limits.EastmoneyPurchaseLimitProvider(http)  # type: ignore[arg-type]

    snapshot = provider.fetch("000834")

    assert http.calls == [("GET", "https://fundf10.eastmoney.com/jjfl_000834.html")]
    assert snapshot.artifact_type == "PURCHASE_LIMIT_HTML"
    assert snapshot.raw_payload.startswith(b"\n    <html>")
    assert len(snapshot.records) == 1
    record = snapshot.records[0]
    assert record.channel_type == "DISTRIBUTION"
    assert record.channel_key == "EASTMONEY_TIANTIAN"
    assert record.channel_name == "天天基金"
    assert record.channel_key != "ALL_DISTRIBUTORS"
    assert record.availability_state == "OPEN"
    assert record.cap_state == "LIMITED"
    assert record.limit_amount == Decimal("10")
    assert record.currency == "CNY"
    assert record.limit_scope == "PER_SHARE"


def test_eastmoney_exchange_traded_share_is_not_sold_by_named_distributor() -> None:
    http = FixtureEastmoneyLimitHttp(
        _eastmoney_html(
            "159513",
            "<tr><th>申购状态</th><td>场内交易</td></tr>",
        )
    )
    provider = limits.EastmoneyPurchaseLimitProvider(http)  # type: ignore[arg-type]

    record = provider.fetch("159513").records[0]

    assert record.channel_key == "EASTMONEY_TIANTIAN"
    assert record.availability_state == "NOT_SOLD"
    assert record.cap_state == "UNKNOWN"
    assert record.limit_amount is None


@pytest.mark.parametrize(
    ("html", "message"),
    [
        (
            _eastmoney_html("000834", "<tr><th>申购状态</th><td>状态字段改名</td></tr>"),
            "unrecognized purchase status",
        ),
        (_eastmoney_html("017653", "<tr><td>申购状态 开放申购</td></tr>"), "does not match"),
    ],
)
def test_eastmoney_limit_provider_fails_closed_on_schema_mismatch(html: str, message: str) -> None:
    http = FixtureEastmoneyLimitHttp(html)
    provider = limits.EastmoneyPurchaseLimitProvider(http)  # type: ignore[arg-type]

    with pytest.raises(ProviderSchemaError, match=message):
        provider.fetch("000834")


def test_eastmoney_keeps_disclosed_but_missing_amount_explicitly_unknown() -> None:
    http = FixtureEastmoneyLimitHttp(
        _eastmoney_html("000834", "<tr><td>申购状态 限大额</td><td>限额稍后公布</td></tr>")
    )
    provider = limits.EastmoneyPurchaseLimitProvider(http)  # type: ignore[arg-type]

    record = provider.fetch("000834").records[0]

    assert record.availability_state == "OPEN"
    assert record.cap_state == "UNKNOWN"
    assert record.limit_amount is None


def test_eastmoney_zero_amount_is_not_stored_as_a_real_cap() -> None:
    http = FixtureEastmoneyLimitHttp(
        _eastmoney_html(
            "003722",
            """
            <tr><td>申购状态</td><td>暂停申购</td></tr>
            <tr><td>日累计申购限额</td><td>0.00美元</td></tr>
            """,
        )
    )
    provider = limits.EastmoneyPurchaseLimitProvider(http)  # type: ignore[arg-type]

    record = provider.fetch("003722").records[0]

    assert record.availability_state == "PAUSED"
    assert record.cap_state == "UNKNOWN"
    assert record.limit_amount is None
    assert record.currency == "USD"


def test_csrc_000834_separates_direct_and_all_distributors_and_keeps_large_pause_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notice_text = """
    大成纳斯达克100交易型开放式指数证券投资基金联接基金调整大额申购业务公告
    基金代码：000834。公告送出日期：2026年6月3日。
    自2026年6月4日起暂停大额申购业务。
    通过本公司直销渠道单日每个基金账户累计申购金额不超过100元；
    通过各代销机构单日每个基金账户累计申购金额不超过10元。
    """
    http = FixtureCsrcLimitHttp(
        834,
        _csrc_detail_html(
            instance_id=1500819,
            published_on="2026-06-03",
            title="大成纳斯达克100ETF联接基金调整大额申购业务公告",
        ),
    )
    monkeypatch.setattr(limits, "_extract_pdf_text", lambda _: notice_text)
    provider = limits.CsrcPurchaseLimitProvider(http)  # type: ignore[arg-type]

    snapshot = provider.fetch("000834", ("000834",))

    assert [method for method, _ in http.calls] == ["POST", "GET", "GET"]
    assert snapshot.artifact_type == "PURCHASE_LIMIT_NOTICE_PDF"
    assert snapshot.raw_payload == b"%PDF-fixture"
    direct = _record_by_channel(snapshot.records, "000834", "DIRECT")
    distribution = _record_by_channel(snapshot.records, "000834", "ALL_DISTRIBUTORS")
    assert direct.availability_state == "OPEN"
    assert direct.cap_state == "LIMITED"
    assert direct.limit_amount == Decimal("100")
    assert distribution.availability_state == "OPEN"
    assert distribution.cap_state == "LIMITED"
    assert distribution.limit_amount == Decimal("10")
    assert direct.effective_from == distribution.effective_from
    assert direct.effective_from is not None
    assert direct.effective_from.isoformat() == "2026-06-04"


def test_csrc_017653_applies_combined_100k_cap_to_direct_and_all_sales(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notice_text = """
    创金合信全球芯片产业股票型发起式证券投资基金（QDII）限制大额申购公告
    A类基金份额代码017653，C类基金份额代码017654。公告送出日期：2026年7月18日。
    自2026年7月21日起，通过所有销售机构和本公司直销渠道单日每个基金账户
    累计申购金额不超过10万元。各类份额的申请金额合并计算。
    """
    http = FixtureCsrcLimitHttp(
        17653,
        _csrc_detail_html(
            instance_id=1532228,
            published_on="2026-07-18",
            title="创金合信全球芯片产业股票型发起式基金限制大额申购业务公告",
        ),
    )
    monkeypatch.setattr(limits, "_extract_pdf_text", lambda _: notice_text)
    provider = limits.CsrcPurchaseLimitProvider(http)  # type: ignore[arg-type]

    snapshot = provider.fetch("017653", ("017653", "017654"))

    purchase_records = [record for record in snapshot.records if record.business_type == "PURCHASE"]
    assert len(purchase_records) == 4
    for share_code in ("017653", "017654"):
        direct = _record_by_channel(purchase_records, share_code, "DIRECT")
        distribution = _record_by_channel(purchase_records, share_code, "ALL_DISTRIBUTORS")
        for record in (direct, distribution):
            assert record.availability_state == "OPEN"
            assert record.cap_state == "LIMITED"
            assert record.limit_amount == Decimal("100000")
            assert record.currency == "CNY"
            assert record.limit_scope == "ALL_SHARES_COMBINED"
            assert record.effective_from is not None
            assert record.effective_from.isoformat() == "2026-07-21"


def test_csrc_000041_discovers_sales_purchase_cap_notice_and_applies_all_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notice_text = """
    关于调整华夏全球精选股票型证券投资基金人民币销售申购、定期定额申购业务上限的公告
    自2026年4月13日起，单个投资者单日累计申购（含定期定额申购）申请
    华夏全球股票（QDII）（人民币）（000041）的金额应不超过人民币1万元。
    特此公告 华夏基金管理有限公司 二〇二六年四月十三日
    """
    http = FixtureCsrcLimitHttp(
        463,
        _csrc_detail_html(
            instance_id=1465933,
            published_on="2026-04-13",
            title="关于调整华夏全球精选股票型证券投资基金人民币销售申购、定期定额申购业务上限的公告",
        ),
    )
    monkeypatch.setattr(limits, "_extract_pdf_text", lambda _: notice_text)
    provider = limits.CsrcPurchaseLimitProvider(http)  # type: ignore[arg-type]

    snapshot = provider.fetch("000041", ("000041", "019549", "019550"))

    direct = _record_by_channel(snapshot.records, "000041", "DIRECT")
    distribution = _record_by_channel(snapshot.records, "000041", "ALL_DISTRIBUTORS")
    for record in (direct, distribution):
        assert record.availability_state == "OPEN"
        assert record.cap_state == "LIMITED"
        assert record.limit_amount == Decimal("10000")
        assert record.currency == "CNY"
        assert record.effective_from == date(2026, 4, 13)
    assert direct.raw_text.startswith("\n    关于调整华夏全球精选")


def test_csrc_002891_keeps_direct_and_distribution_caps_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notice_text = """
    关于调整华夏移动互联灵活配置混合型证券投资基金（QDII）人民币销售
    申购、定期定额申购业务上限的公告
    自2026年7月21日起，单个投资者通过本公司直销机构单日累计申购（含定期定额申购）
    申请华夏移动互联混合（QDII）（人民币）（002891）的金额应不超过人民币1,000元，
    单个投资者通过代销机构单日累计申购（含定期定额申购）申请华夏移动互联混合
    （QDII）（人民币）（002891）的金额应不超过人民币500元。
    """
    http = FixtureCsrcLimitHttp(
        1165,
        _csrc_detail_html(
            instance_id=1534843,
            published_on="2026-07-21",
            title="关于调整华夏移动互联灵活配置混合型证券投资基金（QDII）人民币销售申购、定期定额申购业务上限的公告",
        ),
    )
    monkeypatch.setattr(limits, "_extract_pdf_text", lambda _: notice_text)
    provider = limits.CsrcPurchaseLimitProvider(http)  # type: ignore[arg-type]

    snapshot = provider.fetch("002891", ("002891", "002892", "002893"))

    direct = _record_by_channel(snapshot.records, "002891", "DIRECT")
    distribution = _record_by_channel(snapshot.records, "002891", "ALL_DISTRIBUTORS")
    assert direct.limit_amount == Decimal("1000")
    assert distribution.limit_amount == Decimal("500")
    assert direct.effective_from == distribution.effective_from == date(2026, 7, 21)


def test_csrc_005698_applies_channel_caps_in_each_share_currency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notice_text = """
    华夏全球科技先锋混合型证券投资基金（QDII）调整申购及定期定额申购业务上限的公告
    A类基金份额代码：005698（人民币）、019447（美元现汇）、019448（美元现钞），
    C类基金份额代码：024239。自2026年7月21日起，单个投资者通过本公司直销机构
    单日累计申购申请人民币份额的金额各类别均应不超过人民币1万元，单个投资者通过
    本公司直销机构单日累计申购申请美元份额的金额均应不超过1,600美元；单个投资者
    通过代销机构单日累计申购申请人民币份额的金额各类别均应不超过人民币5,000元，
    单个投资者通过代销机构单日累计申购申请美元份额的金额均应不超过800美元。
    """
    http = FixtureCsrcLimitHttp(
        5254,
        _csrc_detail_html(
            instance_id=1534838,
            published_on="2026-07-21",
            title="华夏全球科技先锋混合型证券投资基金（QDII）调整申购及定期定额申购业务上限的公告",
        ),
    )
    monkeypatch.setattr(limits, "_extract_pdf_text", lambda _: notice_text)
    provider = limits.CsrcPurchaseLimitProvider(http)  # type: ignore[arg-type]

    snapshot = provider.fetch(
        "005698",
        ("005698", "019447", "019448", "024239"),
        share_currencies={
            "005698": "CNY",
            "019447": "USD",
            "019448": "USD",
            "024239": "CNY",
        },
    )

    for share_code in ("005698", "024239"):
        direct = _record_by_channel(snapshot.records, share_code, "DIRECT")
        distribution = _record_by_channel(snapshot.records, share_code, "ALL_DISTRIBUTORS")
        assert (direct.limit_amount, direct.currency) == (Decimal("10000"), "CNY")
        assert (distribution.limit_amount, distribution.currency) == (Decimal("5000"), "CNY")
    for share_code in ("019447", "019448"):
        direct = _record_by_channel(snapshot.records, share_code, "DIRECT")
        distribution = _record_by_channel(snapshot.records, share_code, "ALL_DISTRIBUTORS")
        assert (direct.limit_amount, direct.currency) == (Decimal("1600"), "USD")
        assert (distribution.limit_amount, distribution.currency) == (Decimal("800"), "USD")


def test_csrc_001668_reads_per_share_limits_from_pdf_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notice_text = """
    关于汇添富全球移动互联灵活配置混合型证券投资基金调整大额申购、
    定期定额投资业务限制金额的公告
    公告送出日期：2026年06月09日
    暂停大额申购起始日 2026年06月10日
    下属基金份额的交易代码 001668 015202 015203 006426
    本基金恢复大额申购、大额定期定额投资业务的具体时间将另行公告。
    """
    table_rows = (
        ("下属基金份额的\n交易代码", None, "001668", "015202", "015203", "006426"),
        ("金额单位", None, "人民币元", "人民币元", "人民币元", "美元"),
        ("下属基金份额的\n限制申购金额", None, "700.00", "700.00", "700.00", "100.00"),
        (
            "下属基金份额的\n限制定期定额投\n资金额",
            None,
            "700.00",
            "700.00",
            "700.00",
            "100.00",
        ),
    )
    http = FixtureCsrcLimitHttp(
        1377,
        _csrc_detail_html(
            instance_id=1502713,
            published_on="2026-06-09",
            title="关于汇添富全球移动互联灵活配置混合型证券投资基金调整大额申购、定期定额投资业务限制金额的公告",
        ),
    )
    monkeypatch.setattr(limits, "_extract_pdf_text", lambda _: notice_text)
    monkeypatch.setattr(limits, "_extract_pdf_tables", lambda _: table_rows)
    provider = limits.CsrcPurchaseLimitProvider(http)  # type: ignore[arg-type]

    snapshot = provider.fetch(
        "001668",
        ("001668", "006426", "015202", "015203"),
        share_currencies={
            "001668": "CNY",
            "006426": "USD",
            "015202": "CNY",
            "015203": "CNY",
        },
    )

    expected = {
        "001668": (Decimal("700"), "CNY"),
        "015202": (Decimal("700"), "CNY"),
        "015203": (Decimal("700"), "CNY"),
        "006426": (Decimal("100"), "USD"),
    }
    for share_code, amount in expected.items():
        for business_type in ("PURCHASE", "RECURRING_INVESTMENT"):
            direct = _record_by_channel(snapshot.records, share_code, "DIRECT", business_type)
            distribution = _record_by_channel(
                snapshot.records, share_code, "ALL_DISTRIBUTORS", business_type
            )
            assert (direct.limit_amount, direct.currency) == amount
            assert (distribution.limit_amount, distribution.currency) == amount
            assert direct.cap_state == distribution.cap_state == "LIMITED"


def test_csrc_reads_single_share_limit_table_and_ignores_future_restore_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notice_text = """
    关于调整工银瑞信全球精选股票型证券投资基金大额申购、定期定额投资业务限制金额的公告
    公告送出日期：2026年3月24日
    暂停大额申购起始日 2026年3月25日
    本基金恢复大额申购、定期定额投资业务的具体时间将另行公告。
    """
    table_rows = (
        ("基金主代码", None, "486002"),
        (None, "限制申购金额（单位：人民币元）", "100.00"),
        (None, "限制定期定额投资金额（单位：人民币元）", "100.00"),
    )
    http = FixtureCsrcLimitHttp(
        486002,
        _csrc_detail_html(
            instance_id=1445920,
            published_on="2026-03-24",
            title="关于调整工银瑞信全球精选股票型证券投资基金大额申购、定期定额投资业务限制金额的公告",
        ),
    )
    monkeypatch.setattr(limits, "_extract_pdf_text", lambda _: notice_text)
    monkeypatch.setattr(limits, "_extract_pdf_tables", lambda _: table_rows)
    provider = limits.CsrcPurchaseLimitProvider(http)  # type: ignore[arg-type]

    snapshot = provider.fetch("486002", ("486002",))

    for business_type in ("PURCHASE", "RECURRING_INVESTMENT"):
        direct = _record_by_channel(snapshot.records, "486002", "DIRECT", business_type)
        distribution = _record_by_channel(
            snapshot.records, "486002", "ALL_DISTRIBUTORS", business_type
        )
        assert direct.limit_amount == distribution.limit_amount == Decimal("100")
        assert direct.cap_state == distribution.cap_state == "LIMITED"


def test_csrc_table_limit_remains_distributor_default_when_direct_cap_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notice_text = """
    关于测试基金暂停大额申购、大额定期定额投资的公告
    公告送出日期：2026年7月21日
    暂停大额申购起始日 2026年7月23日
    下属分级基金的交易代码 040046 014978
    每一类基金份额累计申购金额应不超过10元。
    自2026年7月23日起，投资者通过本公司直销机构申购本基金，
    每一类基金份额累计申购金额应不超过100元。
    """
    table_rows = (
        ("下属分级基金的交易代码", None, "040046", "014978"),
        ("下属分级基金的限制申购金额（单位：人民币元）", None, "10.00", "10.00"),
    )
    http = FixtureCsrcLimitHttp(
        40046,
        _csrc_detail_html(
            instance_id=1535057,
            published_on="2026-07-21",
            title="关于测试基金暂停大额申购、大额定期定额投资的公告",
        ),
    )
    monkeypatch.setattr(limits, "_extract_pdf_text", lambda _: notice_text)
    monkeypatch.setattr(limits, "_extract_pdf_tables", lambda _: table_rows)
    provider = limits.CsrcPurchaseLimitProvider(http)  # type: ignore[arg-type]

    snapshot = provider.fetch("040046", ("040046", "014978"))

    direct = _record_by_channel(snapshot.records, "040046", "DIRECT")
    distribution = _record_by_channel(snapshot.records, "040046", "ALL_DISTRIBUTORS")
    assert direct.limit_amount == Decimal("100")
    assert distribution.limit_amount == Decimal("10")


def test_csrc_table_currency_note_overrides_generic_cny_column_label() -> None:
    text = """
    下属分级基金的交易代码 019172 019173 019174 019175。
    注：人民币份额的限制金额单位为人民币元，美元份额的限制金额单位为美元。
    """
    rows = (
        ("下属分级基金的交易代码", None, "019172", "019173", "019174", "019175"),
        (
            "下属分级基金的限制申购金额（单位：人民币元）",
            None,
            "10.00",
            "10.00",
            "1.00",
            "1.00",
        ),
    )

    parsed = limits._table_limits(  # noqa: SLF001
        rows,
        text,
        ("019172", "019173", "019174", "019175"),
        {
            "019172": "CNY",
            "019173": "CNY",
            "019174": "USD",
            "019175": "USD",
        },
    )

    assert parsed["PURCHASE"] == {
        "019172": (Decimal("10"), "CNY"),
        "019173": (Decimal("10"), "CNY"),
        "019174": (Decimal("1"), "USD"),
        "019175": (Decimal("1"), "USD"),
    }


def test_csrc_pause_then_restore_notice_changes_state_on_restoration_date() -> None:
    text = """
    关于测试基金暂停及恢复大额申购（定期定额投资）业务的公告
    公告送出日期：2026年1月9日
    暂停大额申购起始日 2026年1月12日
    自2026年1月16日起，本基金将恢复办理大额申购（定期定额投资）业务。
    """
    rows = (
        ("基金主代码", None, "519696"),
        (None, "限制大额申购金额（单位：元）", "1,000,000"),
    )

    limited = limits._parse_csrc_notice(  # noqa: SLF001
        text,
        ("519696",),
        exchange_traded_codes=frozenset(),
        share_currencies={"519696": "CNY"},
        table_rows=rows,
        as_of_date=date(2026, 1, 15),
        fallback_published_date=date(2026, 1, 9),
    )
    restored = limits._parse_csrc_notice(  # noqa: SLF001
        text,
        ("519696",),
        exchange_traded_codes=frozenset(),
        share_currencies={"519696": "CNY"},
        table_rows=rows,
        as_of_date=date(2026, 1, 16),
        fallback_published_date=date(2026, 1, 9),
    )

    before = _record_by_channel(limited, "519696", "DIRECT")
    after = _record_by_channel(restored, "519696", "DIRECT")
    assert (before.cap_state, before.limit_amount) == ("LIMITED", Decimal("1000000"))
    assert (after.cap_state, after.limit_amount) == ("UNLIMITED", None)
    assert after.effective_from == date(2026, 1, 16)
