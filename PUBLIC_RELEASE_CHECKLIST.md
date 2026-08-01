# Public release checklist

状态说明：`[x]` 已在本地代码层完成；`[ ]` 仍需发布前人工或环境验证。

- [x] 公共仓库来自 committed HEAD 快照，不含私有 `.git` 或旧历史。
- [x] 删除个人 Excel、生成 coverage、真实 Portfolio 与完整第三方 PDF。
- [x] `.env`、`.data/`、本地 override、backup 和缓存已 ignore。
- [x] 默认只绑定 loopback；Portfolio 默认关闭。
- [x] Apache-2.0、NOTICE、免责声明、隐私、数据许可和安全政策已提供。
- [x] README、架构、配置、数据模型、解析、穿透、分析与运维文档已提供。
- [x] CI 仅依赖 fixture，不访问真实 Provider。
- [ ] 在干净机器完成 `docker compose build` 和空 PostgreSQL migration。
- [ ] 完成依赖许可证清单与第三方数据再分发人工复核。
- [ ] 完成 secret scan 人工复核。
- [ ] 确认仓库名称、维护者私密安全联系方式和 GitHub 安全功能。
- [ ] 明确授权后才创建远端或改变 GitHub 可见性。

在全部未完成项关闭前，不应将仓库设为 Public。
