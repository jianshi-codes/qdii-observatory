# 每日维护、停止与重启

本文针对使用 `docker compose` 的本地部署。所有命令都在仓库根目录运行，并使用现有 `.env`。这些操作不会删除 PostgreSQL named volume；不要给 `down` 添加 `--volumes`。

## 电脑开机后启动

```bash
make docker-up
docker compose --env-file .env ps
curl --fail http://127.0.0.1:8000/health
```

`make docker-up` 会执行 `docker compose up --build -d`。backend 等待 PostgreSQL healthy 后自动执行 Alembic migration，再启动 API。Compose 服务配置了 `restart: unless-stopped`；Docker Desktop 随系统启动时，未被手工停止的容器通常会自动恢复，但仍应执行 `ps` 和 health 检查，不要只看容器名称判断可用。

## 每日数据维护

每天需要执行的是净值、场内价格、渠道限额、参考汇率，以及启用扩展的同步：

```bash
make docker-daily
# 等价命令：
docker compose --env-file .env exec backend qdii sync-daily
```

同步后检查：

```bash
docker compose --env-file .env exec backend qdii doctor
docker compose --env-file .env logs --tail=100 backend
```

`sync-daily` 返回 `partial` 时不要把旧值当成今日值；进入“数据运维”页查看 ingestion run 和质量问题。Provider 实时可达不代表数据完整，以本次 run、来源时间和 schema 校验为准。

季报不是每日产生。进入季报披露窗口时可每天执行，平时按需或每周执行：

```bash
docker compose --env-file .env exec backend qdii sync-reports --latest-quarter
docker compose --env-file .env exec backend qdii parse-reports --latest-quarter
docker compose --env-file .env exec backend qdii coverage --latest-quarter
```

## 正常重启

服务已运行、没有修改代码或 `.env` 时：

```bash
make docker-restart
docker compose --env-file .env ps
curl --fail http://127.0.0.1:8000/health
```

`restart` 不会重新构建镜像，也不会应用新的 Compose 配置或环境变量。

修改了代码、依赖、`.env` 或 `compose.yaml` 后，使用完整重建启动：

```bash
make docker-up
docker compose --env-file .env ps
docker compose --env-file .env exec backend qdii doctor
```

`up --build -d` 会重建有变化的镜像并重建需要更新的容器；不会删除数据卷。

## 停止和再次启动

临时停止容器但保留容器定义：

```bash
docker compose --env-file .env stop
docker compose --env-file .env start
```

停止并移除容器与网络、保留数据库 volume：

```bash
make docker-down
# 之后重新启动：
make docker-up
```

不要运行 `docker compose down --volumes`，除非你明确要删除本地数据库并已验证备份。

## 更新代码前后

更新前先备份：

```bash
docker compose --env-file .env exec backend qdii backup
```

完成代码更新后：

```bash
make docker-up
docker compose --env-file .env exec backend qdii doctor
curl --fail http://127.0.0.1:8000/health
```

如果 migration、health 或最小查询失败，保留容器日志和备份，不要自动 reset 数据库。恢复数据库是覆盖性操作，必须按 [operations.md](operations.md) 的确认流程执行。

## 建议频率

| 项目 | 建议频率 |
|---|---|
| `sync-daily` | 每个交易日收盘后一次 |
| `doctor` 和 backend 日志 | 每次同步后 |
| 季报发现、解析、coverage | 披露窗口每日；其他时间按需 |
| 数据库备份 | 代码升级前；有重要新数据后 |
| `make check` | 修改代码或依赖后 |
