# Public release checklist

状态说明：`[x]` 已在当前文件树验证；`[ ]` 仍需发布前人工、托管平台或历史处理。每次公开发布都要重新执行，不能沿用旧勾选。

- [x] 当前 tracked tree 不含个人 Excel、生成 coverage、真实 Portfolio、完整第三方 PDF、`.env` 或 `.data/`。
- [x] `.env`、`.data/`、本地 override、backup 和缓存已 ignore。
- [x] 默认只绑定 loopback；Portfolio 默认开启但初始为空，可通过环境变量关闭。
- [x] Apache-2.0、NOTICE、免责声明、隐私、数据许可和安全政策已提供。
- [x] README、架构、配置、数据模型、解析、穿透、分析与运维文档已提供。
- [x] CI 仅依赖 fixture，不访问真实 Provider。
- [x] 当前工作树已完成 backend/frontend 镜像构建、182 个后端测试、32 个前端测试，并在 `0011_operation_lookback` 受管外部库通过预检。
- [x] 当前 Python/前端依赖已生成许可证清单并检查许可证类别；LGPL/MPL 与 bundled dependency 义务已在 `THIRD_PARTY_NOTICES.md` 标出。
- [x] 已按当前 lockfile/开发环境复核源代码依赖许可证；前端的 BlueOak-1.0.0 与 CC-BY-4.0、Python 的 LGPL/MPL 义务已在 `THIRD_PARTY_NOTICES.md` 标出。
- [x] 已人工检查 Provider fixture：只保留 synthetic 或最小化结构样本，不包含完整第三方页面、PDF、账户数据或 Provider 响应归档。
- [x] 主动科技 Dashboard 没有新增 Provider；只派生现有正式净值、季报和穿透数据。PNG 浏览器依赖 `html-to-image` 为 MIT，真实数据与导出图片不进入 tracked tree。
- [x] 当前 tracked file 已完成 secret、用户路径和个人数据扫描。
- [x] 当前完整 Git 历史已通过 gitleaks；精确 allowlist 只排除 `disclosed_top10_pct` UI 标识产生的两处误报。
- [x] 维护者已明确选择保留现有 Git 历史，并接受作者姓名/邮箱等贡献者身份元数据随 Public 仓库公开；不重写历史，不声称匿名。
- [ ] 确认仓库名称、维护者私密安全联系方式，并启用 Private Vulnerability Reporting、secret protection、Dependabot 和分支保护。
- [x] 维护者已明确授权创建 private remote；切换为 Public 仍需单独确认。

以上未完成项关闭前，不应将仓库设为 Public。若分发预构建镜像或二进制包，还必须从最终产物重新生成精确依赖许可证清单并保留相应 notices；该二进制发布门禁不阻止仅源代码仓库进入 Public review。
