# 数据模型与 universe schema

统一 universe 字段：

- 必填：`representative_code`、`representative_name`、`manager_name`、`canonical_name`、`share_codes`、`region`、`category`、`strategy_type`。
- 可选：`share_names`、`share_currencies`、`wrapper_type`、`tech_scope`、`enabled`。
- `share_codes` 接受逗号、分号、顿号或空白分隔；JSON 也接受数组。
- wrapper：`DIRECT`、`ETF`、`ETF_FEEDER`、`FOF`、`LOF`。
- currency：`CNY`、`USD`、`HKD`。

从公开目录按代码导入时，一个显式选择的份额代码先作为一个独立合同记录进入本地 universe；在没有正式合同或份额关系证据前，不凭名称自动合并 A/C/美元等份额。公开目录原始分类写入 `original_category`；“研究领域”由基金名称与来源分类通过同一启发式规则生成，并同时用于公开导入和基金总览筛选。它不是官方分类。科技细分口径仍由 `tech_scope` 表达并写入科技 exposure family，其他未知字段保持 `UNKNOWN`。

校验覆盖六位代码、代表代码是否属于份额、跨合同重复份额、重复代表代码/合同名、空字段、非法币种与 wrapper。输入允许 1–N 合同。

报告表保留 `source_page_url`、`document_url`、`local_document_path`、`sha256`、公开时间、parser 版本、状态与错误。allocation/holding 行保留原始行和置信度；unresolved 不写成 0。
