# 快速开始

```bash
cp .env.example .env
# 编辑 .env 的示例密码
docker compose up --build
docker compose ps
curl http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
```

首次启动会等待 PostgreSQL 可连接，执行数据库预检和 Alembic migration，通过最新版结构复核后再启动 API。访问 <http://127.0.0.1:5173>。

“我的持仓”默认开启但初始为空，只读写本机数据库，不连接真实账户。如不需要该模块，在 `.env` 设置 `QDII_ENABLE_PORTFOLIO=false` 后重启 backend 与 worker。

如果使用专用外部 PostgreSQL，在 `.env` 设置 `QDII_EXTERNAL_DATABASE_URL` 后改用 `make docker-up-external`。目标 database 默认需预先存在；也可以通过独立管理员 URL 和严格的 `QDII_AUTO_CREATE_DATABASE=true` 显式授权一次性建库。项目不会认领没有有效 Alembic 历史的未知表；详见 [external-postgresql.md](external-postgresql.md)。

打开“数据运维”页，基金公司、来源分类和研究领域可独立使用或组合；候选结果可逐项选择或全选。也可以输入六位基金代码核对后导入。CSV/XLSX/JSON 文件仅作为高级批量入口继续保留；页面提供 XLSX 模板下载，按模板填写后先校验再导入：

```bash
docker compose exec backend qdii validate-universe --file examples/universe.sample.csv
docker compose exec backend qdii import-universe --file examples/universe.sample.csv
docker compose exec backend qdii doctor
```

仓库示例是 synthetic。真实同步会访问你在 Provider 配置中启用的外部来源；先阅读 `DATA_SOURCES.md`。

后续每日同步、停止和重启见 [daily-operations.md](daily-operations.md)。
