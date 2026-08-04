# 数据来源

项目提供可配置的 Provider 抽象，可能访问监管披露、基金管理人、交易所、公开净值/行情页面和公共汇率来源。Provider 默认配置见 `config/providers.example.yaml`。

Provider registry 支持启用/禁用、优先级、timeout、retry、rate limit 和 User-Agent。健康状态固定为 `HEALTHY`、`DEGRADED`、`RATE_LIMITED`、`SCHEMA_CHANGED`、`DISABLED`、`UNKNOWN`。未执行过真实请求时显示 `UNKNOWN` 是有意行为，不能把“配置存在”误报为健康。

公开基金导入目前使用第三方公开的基金公司目录、基金公司产品页和精确代码搜索响应，为用户提供基金公司、来源分类、研究口径和代码选择。该目录不是监管主数据或官方完整名单；最终名称、分类与份额关系应以基金管理人正式资料为准。

启用 Provider 不代表来源认可本项目，也不保证接口长期稳定。使用者负责核对服务条款、访问频率、署名、再分发和地域要求。CI 不访问任何真实 Provider，只使用本地 synthetic/minimized fixture。

每个归档对象应保存来源 URL、抓取时间、MIME、SHA-256、解析器版本和质量问题；来源变更应标记 `SCHEMA_CHANGED`，不能静默填 0。

`qdii doctor` 会检查配置、数据库、migration、数据目录、DNS 可达性、universe、最新报告、最新净值、缓存权限和 Portfolio 开关。DNS 可达不等于来源健康；真实 ingestion 结果与 schema 校验才是证据。
