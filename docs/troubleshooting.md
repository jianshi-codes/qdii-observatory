# 故障排查

- Compose 提示缺少密码：先 `cp .env.example .env` 并修改示例密码。
- API 无法连接数据库：检查 `docker compose ps`、PostgreSQL health 和 `qdii doctor`。
- 页面为空：先导入 universe，再同步/解析报告；空状态不是 0 暴露。
- Provider `SCHEMA_CHANGED`：保留原始 artifact 和错误，不提高 retry 掩盖 schema 变化；用最小 fixture 修 parser。
- 外部 bind mount 被拒绝：目录必须预先存在、可写、有足够容量，且路径需显式配置。
- Portfolio 不显示：这是默认行为；只在理解隐私边界后设置 `QDII_ENABLE_PORTFOLIO=true` 并重建前端。
