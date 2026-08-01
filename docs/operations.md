# 运维、备份与恢复

常用命令：

```bash
make docker-up
make migrate
make doctor
make check
make docker-down
```

`docker compose down` 不带 `--volumes`，不会删除数据卷。重置命令故意不自动执行，必须由用户显式运行并确认目标。

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
