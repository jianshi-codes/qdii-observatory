# 开源抽取审计

## 抽取边界

- 公共工作副本仅由私有仓库当时的 committed `HEAD` 通过 `git archive` 创建。
- 私有仓库的 `.git`、未提交改动、ignored 文件、本地数据库和缓存均未复制。
- 初始复制范围为 committed `HEAD` 中的后端、前端、迁移、测试与文档源码。

## 已删除

- 个人维护的二进制 QDII Excel universe 快照。
- 由本机数据库生成的 2026 Q2 coverage CSV/Markdown。
- 完整第三方季度报告 PDF 测试文件及其项目特定 manifest。
- 任何真实 portfolio、`.env`、`.data`、数据库 dump 和生成缓存（这些内容本来就不在 committed HEAD 快照中）。

## 已改写

- 项目名统一为 QDII Observatory / QDII 基金观察台 / `qdii-observatory`。
- universe、季度边界、Provider、Portfolio 和部署配置改为用户输入及环境配置。
- Portfolio 示例仅使用 synthetic 数据；模块默认关闭。
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

## 推迟到 roadmap

- Provider Health 完整 UI、Starter Packs、更多 parser 格式、可选 LLM Adapter、交易流水和云部署。

## 永不进入公共仓库

- `.env`、`.data/`、数据库 dump、原始缓存、真实持仓与金额、个人代理映射、用户路径、API key、cookie、token。
- 私有仓库 Git 历史、remote、reflog、分支与 GitHub PR 元数据。
