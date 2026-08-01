# 季报解析

流程为 discovery → download → archive → SHA-256 → identity validation → structured parse → quality issues。季度由 CLI 参数决定；`--latest-quarter` 取最近已经结束的自然季度。

解析资产配置、国家/地区、行业、前十大股票、前十大基金和目标 ETF。前十大股票不归一化为 100%；未披露权益、基金持仓和 unresolved 权重分别保存。无法可靠解析的值保持 `null` 并记录问题。

报告公开时间单独保存，使后续分析能区分 `EX_POST` 与 `LIVE_AVAILABLE`。
