# Portfolio 隐私边界

“我的持仓”导航和页面入口始终可见。默认 `QDII_ENABLE_PORTFOLIO=false`；关闭时页面只展示本地启用说明，不注册 import/fee CLI、`/api/portfolio` 或导入接口，不要求也不读取任何持仓数据。`/api/portfolio/capability` 仅返回开关状态和公共模板地址；基金研究功能独立可用。

开启后可使用 ignored 的 `.data/private/portfolio.json`，也可在页面下载 XLSX 模板并选择文件。持有份额为必填主数据；平台市值、持有收益和持有收益率仍需填写为同日参考快照。页面先把文件发送到本机 API 做内存预览校验，只有用户点击“确认导入”才写入本地数据库；原始 XLSX 不由应用持久化。项目不把文件上传到第三方，也不连接真实账户。示例使用虚构平台和 synthetic 金额。

确认导入会把模板中的基金加入 active universe；如果基金已归档则恢复，如果本地尚无该基金则先通过公开基金目录确认并导入。缺少快照日锚点净值时会调用已配置的公开净值来源补齐，因此基金代码会发送给对应公开 Provider。

Evidence 模式为 `PUBLIC`、`REDACTED`、`PRIVATE`，默认 `REDACTED`。公共核心分析 bundle 不包含 Portfolio；任何未来 Portfolio bundle 在 PUBLIC/REDACTED 模式必须删除平台名、内部 ID、现金流备注和自定义私密字段。
