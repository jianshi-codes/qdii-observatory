# 每日维护、停止与重启

本文针对使用 `docker compose` 的本地部署。所有命令都在仓库根目录运行，并使用现有 `.env`。这些操作不会删除 PostgreSQL named volume；不要给 `down` 添加 `--volumes`。

## 电脑开机后启动

```bash
make docker-up
docker compose --env-file .env ps
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/ready
```

`make docker-up` 会执行 `docker compose up --build -d`。backend 等待 PostgreSQL 可连接，执行只读数据库预检和 Alembic migration，通过最新版结构复核后再启动 API；worker 在 backend ready 后启动并领取持久化的数据任务。Compose 服务配置了 `restart: unless-stopped`；Docker Desktop 随系统启动时，未被手工停止的容器通常会自动恢复，但仍应执行 `ps`、health 和 ready 检查，不要只看容器名称判断可用。

使用外部 PostgreSQL 时，开机和代码更新后的启动命令必须替换为 `make docker-up-external`。正常重启、每日同步和停止命令不变。详见 [external-postgresql.md](external-postgresql.md)。

## 每日数据维护

普通用户可直接打开 <http://127.0.0.1:5173/ops>，在“数据准备向导”点击“同步日常数据”。它会同步近 10 天净值、场内价格、当天直销/代销限额和参考汇率；“仅同步今日限额”用于窄范围重试。提交后 API 返回 `202 Accepted`，独立 worker 执行任务，页面每 2 秒读取 PostgreSQL 中的任务状态。刷新或关闭页面不会丢失任务；若已有排队或运行中的操作，新操作返回 409，不会并发重复抓取。

任务结束后仍会显示终态。“部分完成”表示某些基金已有可用数据、另一些失败，不能按全部成功理解。下方“失败与低置信度解析”“限额抓取与渠道覆盖”会按中文错误类型归组；点击展开可查看英文错误码、基金、时间、原始错误和可用来源链接。

“获取季度报告”和“解析报告并计算穿透”是独立步骤：必须先取得最近已结束季度的正式报告，之后才能解析和计算穿透。季报不是每日数据，也不要求先同步限额。

CLI 等价操作如下：

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
docker compose --env-file .env logs --tail=100 worker
```

`sync-daily` 或页面任务返回 `partial` 时不要把旧值当成今日值；进入“数据运维”页查看任务、ingestion run 和质量问题。Provider 实时可达不代表数据完整，以本次 run、来源时间和 schema 校验为准。worker 在运行中被重启时会把该任务标为失败并释放串行锁；已经按基金提交的数据仍保留，用户确认原因后可安全重试。

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
curl --fail http://127.0.0.1:8000/ready
```

`restart` 不会重新构建镜像，也不会应用新的 Compose 配置或环境变量。

修改了代码、依赖、`.env` 或 `compose.yaml` 后，使用完整重建启动：

```bash
make docker-up
docker compose --env-file .env ps
docker compose --env-file .env exec backend qdii doctor
```

`up --build -d` 会重建有变化的镜像并重建需要更新的容器；不会删除数据卷。

外部 PostgreSQL 部署在上述场景使用 `make docker-up-external`，避免切回内置数据库。

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
curl --fail http://127.0.0.1:8000/ready
```

如果预检、migration、ready 或最小查询失败，保留容器日志和备份，不要 stamp、自动 reset 或修改 Alembic 版本。恢复数据库是覆盖性操作，必须按 [operations.md](operations.md) 的确认流程执行。

## 建议频率

| 项目 | 建议频率 |
|---|---|
| `sync-daily` | 每个交易日收盘后一次 |
| `doctor` 和 backend 日志 | 每次同步后 |
| 季报发现、解析、coverage | 披露窗口每日；其他时间按需 |
| 数据库备份 | 代码升级前；有重要新数据后 |
| `make check` | 修改代码或依赖后 |
