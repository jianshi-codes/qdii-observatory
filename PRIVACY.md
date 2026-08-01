# 隐私说明

- 默认 local-first；核心服务不主动上传个人数据。
- Portfolio 默认关闭，关闭时不读取文件、不显示导航、不注册相关 CLI 与 API。
- 开启后只读取 `.data/private/portfolio.json`；该目录被 Git ignore。
- 项目不连接券商、基金销售平台或真实账户。
- Evidence Bundle 默认为 `REDACTED`；核心导出不含平台名、持仓内部 ID、现金流备注或自定义私密字段。
- Provider 请求会把基金代码发送给被启用的公开数据来源；请求边界见 `DATA_SOURCES.md`。
