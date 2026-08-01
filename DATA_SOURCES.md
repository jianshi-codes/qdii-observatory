# 数据来源

项目提供可配置的 Provider 抽象，可能访问监管披露、基金管理人、交易所、公开净值/行情页面和公共汇率来源。Provider 默认配置见 `config/providers.example.yaml`。

启用 Provider 不代表来源认可本项目，也不保证接口长期稳定。使用者负责核对服务条款、访问频率、署名、再分发和地域要求。CI 不访问任何真实 Provider，只使用本地 synthetic/minimized fixture。

每个归档对象应保存来源 URL、抓取时间、MIME、SHA-256、解析器版本和质量问题；来源变更应标记 `SCHEMA_CHANGED`，不能静默填 0。
