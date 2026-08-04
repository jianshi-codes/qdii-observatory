# 披露持仓一致性

模型名固定为 `DISCLOSED_HOLDINGS_BASELINE`。它对用户显式选择的主动基金比较实际基金净值收益与季度披露持仓、已解析底层基金及可选市场代理构成的静态估算收益。

分析起点是 `report.period_end + 1 day`。若该日期早于报告公开日，模式为 `EX_POST`；否则为 `LIVE_AVAILABLE`。输出 coverage、逐日 residual 的均值、MAE、bias、correlation 与状态：

- `CONSISTENT`
- `SLIGHTLY_DIVERGING`
- `LIKELY_EXPOSURE_CHANGED`
- `INSUFFICIENT_DATA`
- `NOT_APPLICABLE`

公开的 `config/fund-analysis-proxies.yaml` 只保存通用一致性阈值，`funds` 默认为空。基金代理来自 ignored 的 `config/fund-analysis-proxies.local.yaml` 并覆盖公开基线；证券标识的本地人工映射同理由 `config/analysis-security-map.local.yaml` 提供。没有可靠代理或近期解释覆盖不足时返回 `INSUFFICIENT_DATA`。正式报告可解析的业绩比较基准应优先于用户代理（基准自动提取与定价映射仍在 roadmap）。模型不识别具体调仓，不输出买卖指令。
