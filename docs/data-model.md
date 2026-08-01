# 数据模型与 universe schema

统一 universe 字段：

- 必填：`representative_code`、`representative_name`、`manager_name`、`canonical_name`、`share_codes`、`region`、`category`、`strategy_type`。
- 可选：`share_names`、`share_currencies`、`wrapper_type`、`tech_scope`、`enabled`。
- `share_codes` 接受逗号、分号、顿号或空白分隔；JSON 也接受数组。
- wrapper：`DIRECT`、`ETF`、`ETF_FEEDER`、`FOF`、`LOF`。
- currency：`CNY`、`USD`、`HKD`。

校验覆盖六位代码、代表代码是否属于份额、跨合同重复份额、重复代表代码/合同名、空字段、非法币种与 wrapper。输入允许 1–N 合同。

报告表保留 `source_page_url`、`document_url`、`local_document_path`、`sha256`、公开时间、parser 版本、状态与错误。allocation/holding 行保留原始行和置信度；unresolved 不写成 0。
