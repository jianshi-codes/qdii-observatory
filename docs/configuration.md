# 配置

配置优先来自环境变量；`.env` 与 `config/*.local.yaml` 不进入 Git。

| 变量 | 默认 | 说明 |
|---|---:|---|
| `QDII_BIND_HOST` | `127.0.0.1` | 宿主机监听地址；公网监听必须显式改为 `0.0.0.0` |
| `QDII_FRONTEND_PORT` | `5173` | 前端端口 |
| `QDII_BACKEND_PORT` | `8000` | API 端口 |
| `QDII_DATABASE_URL` | 本地 SQLite 开发回退 | Docker 中由 Compose 指向独立 PostgreSQL |
| `QDII_EXTERNAL_DATABASE_URL` | 未设置 | 仅供 `make docker-up-external` 使用的目标外部 PostgreSQL database URL |
| `QDII_EXTERNAL_ADMIN_DATABASE_URL` | 未设置 | 仅供一次性外部建库容器使用的维护库 URL |
| `QDII_AUTO_CREATE_DATABASE` | `false` | 必须严格设置为 `true` 才授权创建缺失的目标 database |
| `QDII_RAW_DATA_DIR` | `.data/raw` | 原始来源归档 |
| `QDII_ENABLE_PORTFOLIO` | `false` | Portfolio 总开关 |
| `QDII_PROVIDERS_CONFIG` | `config/providers.local.yaml` | Provider 配置；不存在时读取 example |
| `QDII_CORS_ORIGINS` | 空（`qdii init` 示例为 loopback 前端） | 逗号分隔的精确 origin |

PostgreSQL 默认使用 named volume。若要 bind mount：设置 `QDII_PG_VOLUME_TYPE=bind` 与 `QDII_PG_DATA_SOURCE=./.data/postgres`，先确认目录容量和权限。

默认 Docker 模式固定使用内置 PostgreSQL。外部模式必须显式执行 `make docker-up-external`；只设置 URL 后运行 `make docker-up` 不会切换数据库。外部 database 建议专用；默认必须预先存在，也可以按 [external-postgresql.md](external-postgresql.md) 显式授权一次性自动建库。
