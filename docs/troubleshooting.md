# 故障排查

- Compose 提示缺少密码：先 `cp .env.example .env` 并修改示例密码。
- API 无法连接数据库：检查 `docker compose ps`、PostgreSQL health 和 `qdii doctor`。
- `/ready` 返回 503：查看 backend 日志中的数据库状态；连接失败、migration 不是最新版或核心表不可查询都会阻止 ready。
- backend 报 `CONFLICT`：目标 schema 不是空库，也不能被验证为本项目受管库。保留日志和备份，不要运行 `alembic stamp head`；按 [external-postgresql.md](external-postgresql.md) 核对冲突原因。
- provision 报管理员配置错误：确认自动建库值严格为 `true`，管理员与目标 URL 指向同一主机和端口、维护库已存在、应用 role 已存在，且管理员能创建由该 role 拥有的 database。
- 页面为空：到“数据运维”页从公开信息选择基金或输入六位代码；高级用户也可导入 universe 文件。随后同步/解析报告；空状态不是 0 暴露。
- 基金公司没有候选：该公开公司页可能没有 QDII，先换公司或用六位代码精确查询；不要把普通基金自动归入 QDII。
- Provider `SCHEMA_CHANGED`：保留原始 artifact 和错误，不提高 retry 掩盖 schema 变化；用最小 fixture 修 parser。
- 外部 bind mount 被拒绝：目录必须预先存在、可写、有足够容量，且路径需显式配置。
- “我的持仓”入口可见但提示未启用：当前环境显式设置了 `QDII_ENABLE_PORTFOLIO=false`。删除该覆盖或改为 `true`，并重启 backend 和 worker；入口不依赖前端构建开关。
- Portfolio XLSX 预览失败：按页面中的工作表、行号和错误码修正模板后重新预览；预览不会写数据库。只有“确认导入”会加入/恢复 universe、按需补净值并写入持仓。
