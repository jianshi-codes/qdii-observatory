# 数据来源与质量

Provider registry 允许启用/禁用、优先级、timeout、retry、rate limit 和 User-Agent。状态词汇固定为：`HEALTHY`、`DEGRADED`、`RATE_LIMITED`、`SCHEMA_CHANGED`、`DISABLED`、`UNKNOWN`。

`qdii doctor` 检查配置、数据库、migration、数据目录、Provider 状态、DNS 可达性、universe、最新报告、最新净值、缓存权限与 Portfolio 开关。DNS 可达不等于来源健康；真实 ingestion 结果与 schema 校验才是证据。

CI 禁止访问监管、基金公司、行情或汇率真实端点，全部使用 fixture。
