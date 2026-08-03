from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.ingestion.fund_grouping import (
    public_contract_key,
    reconcile_public_fund_contracts,
)
from backend.app.models import (
    DataQualityIssue,
    FundContract,
    FundReport,
    FundShare,
)


def test_public_names_group_33_share_codes_into_12_contracts() -> None:
    rows = [
        ("中欧基金", "中欧港股数字经济混合发起(QDII)A", "DIRECT"),
        ("中欧基金", "中欧港股数字经济混合发起(QDII)C", "DIRECT"),
        ("创金合信基金", "创金合信全球芯片产业股票发起(QDII)A", "DIRECT"),
        ("创金合信基金", "创金合信全球芯片产业股票发起(QDII)C", "DIRECT"),
        ("华夏基金", "华夏全球科技先锋混合(QDII)A(人民币)", "DIRECT"),
        ("华夏基金", "华夏全球科技先锋混合(QDII)A(美元现汇)", "DIRECT"),
        ("华夏基金", "华夏全球科技先锋混合(QDII)A(美元现钞)", "DIRECT"),
        ("华夏基金", "华夏全球科技先锋混合(QDII)C", "DIRECT"),
        ("华宝基金", "华宝海外科技股票(QDII-LOF)A", "LOF"),
        ("华宝基金", "华宝海外科技股票(QDII-LOF)C", "LOF"),
        ("南方基金", "南方港股数字经济混合发起(QDII)A", "DIRECT"),
        ("南方基金", "南方港股数字经济混合发起(QDII)C", "DIRECT"),
        ("嘉实基金", "嘉实全球互联网股票人民币", "DIRECT"),
        ("嘉实基金", "嘉实全球互联网股票美元现汇", "DIRECT"),
        ("嘉实基金", "嘉实全球互联网股票美元现钞", "DIRECT"),
        ("国海富兰克林基金", "国富全球科技互联混合(QDII)人民币A", "DIRECT"),
        ("国海富兰克林基金", "国富全球科技互联混合(QDII)人民币C", "DIRECT"),
        ("国海富兰克林基金", "国富全球科技互联混合(QDII)美元现汇A", "DIRECT"),
        ("国海富兰克林基金", "国富全球科技互联混合(QDII)美元现汇C", "DIRECT"),
        ("富国基金", "富国全球科技互联网股票(QDII)A", "DIRECT"),
        ("富国基金", "富国全球科技互联网股票(QDII)C", "DIRECT"),
        ("富国基金", "富国全球科技互联网股票(QDII)D", "DIRECT"),
        ("广发基金", "广发全球科技三个月定开混合(QDII)人民币A", "DIRECT"),
        ("广发基金", "广发全球科技三个月定开混合(QDII)人民币C", "DIRECT"),
        ("广发基金", "广发全球科技三个月定开混合(QDII)美元A", "DIRECT"),
        ("广发基金", "广发全球科技三个月定开混合(QDII)美元C", "DIRECT"),
        ("景顺长城基金", "景顺长城全球半导体芯片股票A(QDII-LOF)(人民币)", "LOF"),
        ("景顺长城基金", "景顺长城全球半导体芯片股票A(QDII-LOF)(美元现汇)", "LOF"),
        ("景顺长城基金", "景顺长城全球半导体芯片股票C(QDII-LOF)(人民币)", "LOF"),
        ("浦银安盛基金", "浦银安盛全球智能科技(QDII)A", "DIRECT"),
        ("浦银安盛基金", "浦银安盛全球智能科技(QDII)C", "DIRECT"),
        ("银华基金", "银华海外数字经济量化选股混合发起式(QDII)A", "DIRECT"),
        ("银华基金", "银华海外数字经济量化选股混合发起式(QDII)C", "DIRECT"),
    ]
    keys = [public_contract_key(*row) for row in rows]
    assert len(rows) == 33
    assert len(set(keys)) == 12


def test_reconcile_keeps_preferred_report_and_reparents_all_shares(
    db_session: Session,
) -> None:
    primary = FundContract(
        canonical_name="富国全球科技互联网股票(QDII)A",
        manager_name="富国基金",
        representative_code="100055",
        wrapper_type="DIRECT",
        is_user_selected=True,
    )
    duplicate = FundContract(
        canonical_name="富国全球科技互联网股票(QDII)C",
        manager_name="富国基金",
        representative_code="022184",
        wrapper_type="DIRECT",
        is_user_selected=True,
    )
    db_session.add_all([primary, duplicate])
    db_session.flush()
    db_session.add_all(
        [
            FundShare(
                fund_contract_id=primary.id,
                share_code="100055",
                share_class="A",
                currency="CNY",
            ),
            FundShare(
                fund_contract_id=duplicate.id,
                share_code="022184",
                share_class="C",
                currency="CNY",
            ),
        ]
    )
    parsed = FundReport(
        fund_contract_id=primary.id,
        report_type="QUARTERLY",
        report_year=2026,
        report_quarter=2,
        period_end=date(2026, 6, 30),
        source_provider="CSRC_EID",
        parse_status="parsed",
        local_document_path="reports/100055.pdf",
    )
    failed = FundReport(
        fund_contract_id=duplicate.id,
        report_type="QUARTERLY",
        report_year=2026,
        report_quarter=2,
        period_end=date(2026, 6, 30),
        source_provider="CSRC_EID",
        parse_status="failed_with_reason",
        local_document_path="reports/022184.pdf",
    )
    db_session.add_all([parsed, failed])
    db_session.flush()
    db_session.add(
        DataQualityIssue(
            fund_contract_id=duplicate.id,
            fund_report_id=failed.id,
            issue_code="REPORT_PARSE_FAILED",
            severity="ERROR",
            status="OPEN",
            message="share code did not match main code",
            details={},
        )
    )
    db_session.commit()

    result = reconcile_public_fund_contracts(db_session)

    assert result.contracts_before == 2
    assert result.contracts_after == 1
    assert result.groups_merged == 1
    contract = db_session.scalar(select(FundContract))
    assert contract is not None
    assert contract.representative_code == "100055"
    assert {share.share_code for share in contract.shares} == {"100055", "022184"}
    report = db_session.scalar(select(FundReport))
    assert report is not None
    assert report.id == parsed.id
    assert report.parse_status == "parsed"
    assert db_session.scalar(select(func.count(FundReport.id))) == 1
    issue = db_session.scalar(select(DataQualityIssue))
    assert issue is not None
    assert issue.status == "RESOLVED"
    assert issue.fund_contract_id == contract.id
    assert issue.fund_report_id is None
