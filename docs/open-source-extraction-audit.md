# 开源发布审计边界

## 抽取边界

- 初始公共工作副本由源仓库当时的 committed `HEAD` 通过 `git archive` 创建，未复制源仓库 `.git`、ignored 文件、本地数据库和缓存。
- 当前工作副本此后已有自己的 Git 历史；发布前仍需检查该历史中的作者身份、提交内容和已删除对象，不能把“初始未复制旧历史”当作当前历史已匿名的证明。
- 当前代码审计范围包括后端、前端、迁移、测试、配置、模板和文档源码；本地 `.data/` 只用于运行，永不进入发布物。

## 已删除

- 个人维护的二进制 QDII universe 和 Portfolio 工作簿。
- 由本机数据库生成的 coverage、报告、日志与截图。
- 完整第三方季度报告 PDF 测试文件及其项目特定 manifest。
- 任何真实 Portfolio、`.env`、`.data`、数据库 dump 和生成缓存。

## 已改写

- 项目名统一为 QDII Observatory / QDII 基金观察台 / `qdii-observatory`。
- universe、季度边界、Provider、Portfolio 和部署配置改为用户输入及环境配置。
- Portfolio 示例与模板不含用户行；模块默认关闭。
- 基金代理从 tracked 配置移至 ignored 的 `config/fund-analysis-proxies.local.yaml`；公开基线只保留通用一致性规则。
- 文档、测试与 CI 改为公开、可复现、无真实网络依赖的边界。

## 保留的核心能力

- 季报发现、归档、哈希、解析及质量问题记录。
- 净值、场内价格、费率、限额与汇率的 provider 抽象。
- 合同份额、ETF 联接、指数族、基金持仓和 direct/look-through 暴露。
- FastAPI、React、本地 PostgreSQL、Alembic 与确定性 coverage 输出。

## 可选能力

- Portfolio 是显式环境开关控制的本地扩展。
- Provider 可按本地配置启用、禁用和排序。
- 公开示例基金只用于演示输入格式，不构成默认投资池。

## 每次发布仍需复核

- 完整 Git 历史的 secret 与作者身份元数据。
- Python、前端和 GitHub Actions 的依赖许可证与已知漏洞。
- fixture、手工证券映射、文档链接和第三方数据再分发依据。
- README、CHANGELOG、ROADMAP 与实际功能、默认开关和迁移头是否一致。

## 永不进入公共仓库

- `.env`、`.data/`、数据库 dump、原始缓存、真实持仓与金额、个人代理映射、用户路径、API key、cookie、token。
- 源仓库 Git 历史、remote、reflog、分支与托管平台 PR 元数据。
