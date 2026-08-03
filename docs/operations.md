# 运维、备份与恢复

常用命令：

```bash
make docker-up
make docker-up-external
make docker-restart
make docker-daily
make migrate
make doctor
make check
make docker-down
```

`docker compose down` 不带 `--volumes`，不会删除数据卷。重置命令故意不自动执行，必须由用户显式运行并确认目标。

日常启动、交易日同步、正常重启、配置变更后的重建和停止方式见 [daily-operations.md](daily-operations.md)。其中 `restart` 不重建镜像，也不会应用新的 `.env`；代码或配置变化后应使用 `make docker-up`。

外部 PostgreSQL 部署在代码或配置变化后应使用 `make docker-up-external`。启动前状态识别、冲突拒绝和 `/ready` 语义见 [external-postgresql.md](external-postgresql.md)。只有显式配置管理员 URL 和 `QDII_AUTO_CREATE_DATABASE=true` 才会按需创建 database；项目不会对未知库执行 `alembic stamp`。

页面触发的数据准备任务保存在 `data_operation`，由独立 worker 串行执行。API 返回 202 后不等待抓取或解析完成；检查任务终态、ingestion run 和质量问题三者，不能把 `partial` 当成成功。worker 意外重启会将中断任务标为失败并释放任务槽，不会伪造完成状态。

## 备份

```bash
qdii backup
```

PostgreSQL 使用 custom-format `pg_dump`；SQLite 开发回退复制数据库文件。输出在 ignored 的 `.data/backups/`。

## 恢复

恢复会覆盖当前数据库对象，先停止写入并另做备份：

```bash
qdii restore --file .data/backups/<file> --confirm
```

PostgreSQL 恢复需要本机 `pg_restore`。恢复后运行 migration、`qdii doctor` 和最小查询验证。
