# Portfolio 隐私边界

“我的持仓”导航、页面入口和本地数据能力默认开启，初始不包含任何个人数据。设置 `QDII_ENABLE_PORTFOLIO=false` 并重启 backend 与 worker 后，页面只展示本地启用说明，不注册 import/fee CLI、`/api/portfolio` 或导入接口，不要求也不读取任何持仓数据。`/api/portfolio/capability` 仅返回开关状态和公共模板地址；基金研究功能独立可用。

开启后可使用 ignored 的 `.data/private/portfolio.json`，也可在页面下载 XLSX 模板并选择文件。持有份额为必填主数据；平台市值、持有收益和持有收益率仍需填写为同日参考快照。页面先把文件发送到本机 API 做内存预览校验，只有用户点击“确认导入”才写入本地数据库；原始 XLSX 不由应用持久化。项目不把文件上传到第三方，也不连接真实账户。示例使用虚构平台和 synthetic 金额。

确认导入会把模板中的基金加入 active universe；如果基金已归档则恢复，如果本地尚无该基金则先通过公开基金目录确认并导入。缺少快照日锚点净值时会调用已配置的公开净值来源补齐，因此基金代码会发送给对应公开 Provider。

核心分析 Evidence 模式为 `PUBLIC`、`REDACTED`、`PRIVATE`，默认 `REDACTED`；公共核心 bundle 不包含 Portfolio。

持仓页的“导出 AI 分析”是单独的本地 `PRIVATE_FINANCIAL_DATA_WITH_IDENTIFIERS_REDACTED` JSON：保留总资产、份额、收益、定投金额、现金流和用户备注，只删除平台名以及本地持仓、基金和重叠关系的数据库 ID。生成和预览不会发出网络请求，复制也只写入本机剪贴板；用户把内容粘贴到 ChatGPT 或其他服务后，数据即离开本项目的本地边界。该导出不得用于公开 Issue、PR、截图或公共 Evidence Bundle。
