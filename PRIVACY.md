# 隐私说明

- 默认 local-first；核心服务不主动上传个人数据。
- Portfolio 数据能力默认开启，但初始为空；可设置 `QDII_ENABLE_PORTFOLIO=false` 并重启来关闭，此时不读取数据，也不注册敏感 CLI 与 API。
- 启用时可读取 Git ignored 的 `.data/private/portfolio.json`，或在本机页面预览并确认导入 XLSX；应用不持久化原始 XLSX。
- 项目不连接券商、基金销售平台或真实账户。
- 项目不内置遥测、广告 SDK 或远程错误上报；本地日志、截图和备份仍可能包含敏感上下文，应按私密数据处理。
- Evidence Bundle 默认为 `REDACTED`；核心导出不含平台名、持仓内部 ID、现金流备注或自定义私密字段。
- Provider 请求会把基金代码发送给被启用的公开数据来源；请求边界见 `DATA_SOURCES.md`。
