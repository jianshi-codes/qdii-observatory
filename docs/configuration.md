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
| `QDII_MANAGED_DATA_ROOT` | 未设置（Docker 中为 `/data`） | 允许在这个已存在的受管根目录下创建缺失的数据子目录；不会授权创建根目录本身或其他外部路径 |
| `QDII_ENABLE_PORTFOLIO` | `true` | Portfolio 总开关；设为 `false` 后重启可关闭持仓 API 与数据能力 |
| `QDII_PROVIDERS_CONFIG` | `config/providers.local.yaml` | Provider 配置；不存在时读取 example |
| `QDII_CORS_ORIGINS` | 空（`qdii init` 示例为 loopback 前端） | 逗号分隔的精确 origin |

PostgreSQL 默认使用 named volume。若要 bind mount：设置 `QDII_PG_VOLUME_TYPE=bind` 与 `QDII_PG_DATA_SOURCE=./.data/postgres`，先确认目录容量和权限。

默认 Docker 模式固定使用内置 PostgreSQL。外部模式必须显式执行 `make docker-up-external`；只设置 URL 后运行 `make docker-up` 不会切换数据库。外部 database 建议专用；默认必须预先存在，也可以按 [external-postgresql.md](external-postgresql.md) 显式授权一次性自动建库。

## 本地研究覆盖配置

`qdii init` 会在文件不存在时创建以下 ignored 文件，不覆盖已有内容：

- `config/fund-analysis-proxies.local.yaml`：按基金配置市场代理、对齐覆盖和可选一致性阈值；在公开的空基金基线上合并，本地字段优先。
- `config/analysis-security-map.local.yaml`：补充或覆盖披露证券标识到行情代码的人工映射；相同证券代码和市场组合由本地条目优先。

可分别从 `config/fund-analysis-proxies.example.yaml` 和 `config/analysis-security-map.example.yaml` 复制结构。公开仓库只保留通用规则、synthetic 示例和可复用的公开证券映射；用户基金代理不得加入跟踪文件。
