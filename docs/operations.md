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

外部 PostgreSQL 部署在代码或配置变化后应使用 `make docker-up-external`。启动前状态识别、冲突拒绝和 `/ready` 语义见 [external-postgresql.md](external-postgresql.md)。项目不会自动创建 database，也不会对未知库执行 `alembic stamp`。

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
