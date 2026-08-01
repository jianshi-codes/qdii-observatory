# Portfolio 隐私边界

默认 `QDII_ENABLE_PORTFOLIO=false`。关闭时不显示 Portfolio 导航，不注册 import/fee CLI 或 `/api/portfolio`，不要求也不读取任何 Portfolio 文件；基金研究功能独立可用。

开启时只读取 `.data/private/portfolio.json`。项目不上传文件、不连接真实账户。示例使用虚构平台和 synthetic 金额。

Evidence 模式为 `PUBLIC`、`REDACTED`、`PRIVATE`，默认 `REDACTED`。公共核心分析 bundle 不包含 Portfolio；任何未来 Portfolio bundle 在 PUBLIC/REDACTED 模式必须删除平台名、内部 ID、现金流备注和自定义私密字段。
