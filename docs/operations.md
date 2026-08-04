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

外部 PostgreSQL 部署在代码或配置变化后应使用 `make docker-up-external`。启动前状态识别、冲突拒绝和 `/ready` 语义见 [external-postgresql.md](external-postgresql.md)。只有显式配置管理员 URL 和 `QDII_AUTO_CREATE_DATABASE=true` 才会按需创建 database；项目不会对未知库执行 `alembic stamp`。

页面触发的数据准备任务保存在 `data_operation`，由独立 worker 串行执行。API 返回 202 后不等待抓取或解析完成；检查任务终态、ingestion run 和质量问题三者，不能把 `partial` 当成成功。worker 意外重启会将中断任务标为失败并释放任务槽，不会伪造完成状态。

“我的持仓”页的“刷新并触发今日定投”按钮复用同一条 `sync-daily` 队列，只同步当前持仓涉及的基金。工作日点击后，每个启用计划按“持仓 + 申购日”幂等生成一笔本地订单；重复点击不会重复下单。订单先显示为“等待确认”，保存扣款、费率、净买入、申购日和预计 T+ 确认日，此时不进入本金和份额。后续刷新取得申购日对应的来源净值后，订单才变为“已确认”，并以该净值增加本地估算份额及本金。预计确认日只按工作日估算，暂不覆盖法定节假日；这里的“已确认”表示公开净值已经支持本地计算，不是基金销售平台的真实成交凭证。

持仓估值以用户提供的同日平台快照为基线、以真实持有份额驱动后续变化：`参考市值 = 平台快照市值 + 快照份额 ×（最新单位净值 - 快照锚点净值）+ 快照后已确认定投份额 × 最新单位净值`。这样保存快照当天会精确保留平台市值，后续净值变化和最新日收益仍按真实份额计算。平台快照市值不用于反推份额。持仓收益率使用 `快照持有收益 ÷ 快照持有收益率` 得到的平台隐含成本作为固定基线；只有该口径不可用时才回退到 `快照市值 - 快照持有收益`。已确认定投以扣款总额增加成本、以确认净额和来源净值增加份额；等待确认的订单不进入份额、本金或收益。持仓明细的“最新涨跌”和“最新日收益”均显示对应净值日，避免把旧净值误认为当日数据。

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
