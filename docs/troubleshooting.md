# 故障排查

- Compose 提示缺少密码：先 `cp .env.example .env` 并修改示例密码。
- API 无法连接数据库：检查 `docker compose ps`、PostgreSQL health 和 `qdii doctor`。
- `/ready` 返回 503：查看 backend 日志中的数据库状态；连接失败、migration 不是最新版或核心表不可查询都会阻止 ready。
- backend 报 `CONFLICT`：目标 schema 不是空库，也不能被验证为本项目受管库。保留日志和备份，不要运行 `alembic stamp head`；按 [external-postgresql.md](external-postgresql.md) 核对冲突原因。
- 页面为空：到“数据运维”页从公开信息选择基金或输入六位代码；高级用户也可导入 universe 文件。随后同步/解析报告；空状态不是 0 暴露。
- 基金公司没有候选：该公开公司页可能没有 QDII，先换公司或用六位代码精确查询；不要把普通基金自动归入 QDII。
- Provider `SCHEMA_CHANGED`：保留原始 artifact 和错误，不提高 retry 掩盖 schema 变化；用最小 fixture 修 parser。
- 外部 bind mount 被拒绝：目录必须预先存在、可写、有足够容量，且路径需显式配置。
- Portfolio 不显示：这是默认行为；只在理解隐私边界后设置 `QDII_ENABLE_PORTFOLIO=true` 并重建前端。
