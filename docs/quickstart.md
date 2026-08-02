# 快速开始

```bash
cp .env.example .env
# 编辑 .env 的示例密码
docker compose up --build
docker compose ps
curl http://127.0.0.1:8000/health
```

首次启动会等待 PostgreSQL、执行 Alembic migration，再启动 API。访问 <http://127.0.0.1:5173>。

打开“数据运维”页，选择基金公司、来源分类、研究口径和具体基金，或输入六位基金代码核对后导入。CSV/XLSX/JSON 文件仅作为高级批量入口继续保留：

```bash
docker compose exec backend qdii validate-universe --file examples/universe.sample.csv
docker compose exec backend qdii import-universe --file examples/universe.sample.csv
docker compose exec backend qdii doctor
```

仓库示例是 synthetic。真实同步会访问你在 Provider 配置中启用的外部来源；先阅读 `DATA_SOURCES.md`。

后续每日同步、停止和重启见 [daily-operations.md](daily-operations.md)。
