# 配置

配置优先来自环境变量；`.env` 与 `config/*.local.yaml` 不进入 Git。

| 变量 | 默认 | 说明 |
|---|---:|---|
| `QDII_BIND_HOST` | `127.0.0.1` | 宿主机监听地址；公网监听必须显式改为 `0.0.0.0` |
| `QDII_FRONTEND_PORT` | `5173` | 前端端口 |
| `QDII_BACKEND_PORT` | `8000` | API 端口 |
| `QDII_DATABASE_URL` | 本地 SQLite 开发回退 | Docker 中由 Compose 指向独立 PostgreSQL |
| `QDII_RAW_DATA_DIR` | `.data/raw` | 原始来源归档 |
| `QDII_ENABLE_PORTFOLIO` | `false` | Portfolio 总开关 |
| `QDII_PROVIDERS_CONFIG` | `config/providers.local.yaml` | Provider 配置；不存在时读取 example |
| `QDII_CORS_ORIGINS` | loopback 前端 | 逗号分隔的精确 origin |

PostgreSQL 默认使用 named volume。若要 bind mount：设置 `QDII_PG_VOLUME_TYPE=bind` 与 `QDII_PG_DATA_SOURCE=./.data/postgres`，先确认目录容量和权限。
