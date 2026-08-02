# 数据来源与质量

Provider registry 允许启用/禁用、优先级、timeout、retry、rate limit 和 User-Agent。状态词汇固定为：`HEALTHY`、`DEGRADED`、`RATE_LIMITED`、`SCHEMA_CHANGED`、`DISABLED`、`UNKNOWN`。

`qdii doctor` 检查配置、数据库、migration、数据目录、Provider 状态、DNS 可达性、universe、最新报告、最新净值、缓存权限与 Portfolio 开关。DNS 可达不等于来源健康；真实 ingestion 结果与 schema 校验才是证据。

公开基金发现使用第三方公开基金公司目录、基金公司产品页和精确代码搜索响应。它们用于帮助用户选择和录入，不是监管主数据，也不构成官方完整清单。每次精确代码导入都会在本地归档原始响应、来源 URL 和 SHA-256；字段缺失、非 QDII 或 schema 变化时导入失败，不使用名称猜测补齐。

CI 禁止访问监管、基金公司、行情或汇率真实端点，全部使用 fixture。
