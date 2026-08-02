# 外部 PostgreSQL 模式

外部模式适合连接已经由用户或平台管理员创建的专用 PostgreSQL database。项目不会创建 PostgreSQL role 或 database，也不会自动认领未知表。当前部署基线和持续验证使用 PostgreSQL 16。

## 前置条件

- 目标 database 已存在，建议只供本项目使用；不要与其他应用共用默认 schema。
- 连接用户拥有 database 的 `CONNECT` 权限，以及目标 schema 的建表、修改表、创建索引和约束权限。由该用户拥有 database 是最简单的配置。
- Docker 主机能够解析并访问外部 PG 地址；云数据库的防火墙、TLS 和证书要求已配置。
- URL 中的特殊字符已经百分号编码；真实 URL 只写入 ignored 的 `.env`，不要提交到 Git。

在 `.env` 中设置：

```dotenv
QDII_EXTERNAL_DATABASE_URL=postgresql+psycopg://user:encoded-password@db.example:5432/qdii_observatory
```

这里的 database `qdii_observatory` 必须预先存在。仅有 PostgreSQL 实例而没有这个 database 时，连接会失败，项目不会越权创建它。

## 启动和验证

```bash
make docker-up-external
docker compose --env-file .env -f compose.yaml -f compose.external.yaml ps
curl --fail http://127.0.0.1:8000/ready
```

外部 overlay 会让内置 `postgres` 服务进入非默认 profile，因此不会启动本地 PG 容器。backend 只读取 `QDII_EXTERNAL_DATABASE_URL`。不要用 `make docker-up` 代替上面的外部启动命令；默认命令始终选择内置 PostgreSQL。

正常 `restart`、每日同步和停止仍可使用：

```bash
make docker-restart
make docker-daily
make docker-down
```

代码、镜像、Compose 或 `.env` 变化后，外部模式必须再次执行 `make docker-up-external`，否则不会应用新配置。

## 启动前数据库判定

backend 在执行 migration 前先做只读预检：

| 状态 | 判定 | 行为 |
|---|---|---|
| `EMPTY` | 默认 schema 没有表 | 允许 Alembic 从零建表 |
| `MANAGED` | 存在本项目已知的单一 Alembic revision，核心表指纹有效，且没有未知表 | 允许升级；升级后再次核对最新版结构 |
| `CONFLICT` | 有表但没有 Alembic 记录、版本未知/多值、核心表不符、存在未知表，或最新版结构与应用元数据不一致 | 在 migration 前退出，不写表、不 stamp |

最新版结构核对使用 Alembic metadata comparison。表、字段类型、可空性、索引或约束等可检测漂移会阻止 API 启动。旧版受管库先核对核心表指纹，再按正常 migration 升级，并在升级后执行完整结构复核。

项目没有调用 `alembic stamp` 的启动路径。不要对未知数据库手工运行 `alembic stamp head`：它只写入版本号，不创建或验证真实结构，反而可能伪造“已受管”状态。

查看拒绝原因：

```bash
docker compose --env-file .env -f compose.yaml -f compose.external.yaml logs --tail=100 backend
```

冲突时保留日志和数据库备份。不要通过删除 `alembic_version`、改版本号或 reset 数据库绕过检查；应先在数据库副本中确认来源和结构，再制定显式迁移方案。

## `/health` 与 `/ready`

- `/health` 是进程存活检查，不访问数据库。
- `/ready` 查询数据库、读取当前 Alembic revision，并对核心表执行最小查询；连接失败、版本不是最新或核心表不可查询时返回 HTTP 503。

Compose backend healthcheck 使用 `/ready`，因此 frontend 只会在数据库真正可用后启动。`/ready` 不替代启动时的完整结构预检。
