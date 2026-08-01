# Parser Fixture Contribution Kit

每个 fixture 贡献应包含：最小输入、期望解析 JSON、报告类型、基金管理人（如适用）、异常说明、来源和再分发许可依据。

优先级：synthetic > 最小匿名化 > 明确可再分发的公开片段。不要提交完整第三方 PDF、个人账户数据、cookie/token 或由本地数据库生成的结果。

测试必须离线：Provider transport 用本地 HTML/JSON/bytes，parser 断言 identity、表格分类、null/unresolved 和质量问题。schema drift 应产生显式失败，而不是空结果。
