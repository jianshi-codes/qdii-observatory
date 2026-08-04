# Changelog

All notable changes will be documented here. This project follows Keep a Changelog conventions and uses semantic prerelease versions.

## [Unreleased]

### Added

- 从公开目录按基金公司、来源分类、研究领域或精确代码选择基金，并支持 XLSX universe 模板。
- 数据准备任务队列、单基金/全量季度补齐、每日 5/10 日历日同步、Provider health 与中文质量问题归组。
- 可选本地 Portfolio：XLSX 预览确认导入、手工维护、份额主导估值和幂等定投待确认/确认台账。
- 持仓一致性可在页面预览并复制完整财务 JSON 或 ChatGPT 研究提示词；平台名与数据库 ID 自动删除。
- 外部 PostgreSQL Compose 模式、显式授权自动建库、空库/受管库/冲突库预检和数据库查询型 `/ready`。

### Changed

- 基金代理改为 ignored 本地 override；公开基线不再包含特定基金研究配置。
- 季报下载、解析与穿透和每日净值/限额/汇率维护在 UI 中按频率与范围分组。
- 基金详情页的每日涨跌幅使用红涨绿跌柱状图；基金总览保持原样。

### Fixed

- 修复报告表格和申购限额多来源解析、数据任务阻塞/错误终态、覆盖表自动刷新及当日净值覆盖计数。
- 修复 Portfolio 快照、份额、市值、收益、费率和 T+ 定投确认之间的计算与展示一致性。
- 修复 `qdii init` 生成与解析器不兼容的本地研究配置格式。
- 升级 React Router 8.3、Vite 7 和测试工具链，消除当前前端 high 级依赖告警；开发/构建基线调整为 Node.js 22.22+。
- 将 GitHub Actions 固定到已核对的完整提交 SHA，并限制各 CI job 的最长运行时间。
