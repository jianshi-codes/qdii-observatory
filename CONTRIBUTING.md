# 贡献指南

欢迎修复 Provider、增加 parser fixture、改进数据质量诊断、测试和文档。

## 开发流程

1. 从小范围 Issue 或明确问题开始。
2. 安装 Python/前端依赖，所有 Provider 测试使用本地 fixture。
3. 运行 `make check`；涉及迁移时从空 PostgreSQL 执行 `alembic upgrade head`。
4. 运行 `git diff --check`，检查 `git status --short --ignored` 与 `git diff --cached`，确认没有本地数据或生成物进入提交。
5. PR 说明来源、数据许可、行为变化、测试和风险。

Python 使用 ruff、mypy、pytest；前端使用 ESLint、TypeScript、Vitest 和 Vite build。不要顺手重构无关代码。

## Provider 贡献

Provider 必须有 timeout、retry、rate limit、User-Agent、schema drift 错误和 fixture 测试。CI 中不得访问真实网络。新增来源前记录条款与再分发边界。

## Parser fixture

优先提交 synthetic、最小化或匿名化 fixture，并附期望 JSON、报告类型、基金管理人（如适用）、异常说明和许可依据。完整流程见 `docs/contributing-parser-fixtures.md`。

## UI 证据与截图

优先使用 synthetic fixture 构造界面。截图前清除真实持仓、平台名、基金组合、任务日志、文件名、主机路径、数据库地址和浏览器个人信息；PR 只提交证明变化所需的最小画面。无法确认已脱敏时不要上传截图。

## 禁止提交

真实个人持仓、金额、平台内部 ID、账户数据、`.env`、`.data`、本地 override、日志、cookie、token、API key、数据库 dump、完整第三方原始数据或无法证明可再分发的 PDF。模板 XLSX 可以跟踪，但填入真实数据后的工作簿不能提交。
