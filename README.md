# QDII Observatory（QDII 基金观察台）

一个面向中国大陆 QDII 基金的、本地优先、来源可追溯的研究工作台。它把基金 universe、正式季报、每日净值、场内价格、基金关系和解析质量放进同一套可审计数据模型，并支持基金暴露对比和按需运行“披露持仓一致性”基线。

> English summary: QDII Observatory is a local-first, source-traceable workbench for mainland China QDII funds. It imports user-defined universes, archives and parses official reports, stores NAV and exchange prices separately, computes look-through exposure, and evaluates disclosed-holdings consistency. It is not an advisory or trading system.

## 它解决什么问题

- 任意 1–N 只基金，不要求固定名单或数量；可按基金公司、来源分类、研究口径选择，或输入六位基金代码，从公开信息核对后导入。
- 识别同合同份额、ETF 联接、同指数族和报告基金持仓。
- 保存来源 URL、原始文件本地路径、SHA-256、解析状态和质量问题。
- 区分 NAV、场内价格和溢价率；比较国家、行业、前十大持仓、净值与相关性。
- 对显式选择的主动基金运行 `DISCLOSED_HOLDINGS_BASELINE`，输出 coverage、residual、MAE、bias、correlation 和中性一致性状态。

## 它不是什么

项目不调用 LLM、不连接券商账户、不自动交易、不生成买卖指令，也不能从季度披露中识别真实调仓。数据可能延迟、错误或不完整；所有输出仅用于研究，不构成投资建议。详见 [DISCLAIMER.md](DISCLAIMER.md)。

## 支持的数据

- 中国大陆 QDII 基金合同与 A/C/D/E/F/I、人民币/美元等份额。
- 季度报告中的资产、国家/地区、行业、前十大股票、前十大基金和目标 ETF。
- 每日基金净值、场内价格、渠道限额、公开费率和参考汇率。
- direct / look-through 暴露、持仓重叠、净值相关性和披露持仓一致性结果。

原始第三方数据不自动受 Apache-2.0 覆盖，默认只保存在本地 `.data/`；详见 [DATA_LICENSE.md](DATA_LICENSE.md) 和 [DATA_SOURCES.md](DATA_SOURCES.md)。

## 5 分钟启动

```bash
git clone <your-fork-or-local-repository-url> qdii-observatory
cd qdii-observatory
cp .env.example .env
# 修改 .env 中的示例数据库密码
docker compose up --build
```

默认仅绑定 `127.0.0.1`。打开 <http://127.0.0.1:5173>；API 文档位于 <http://127.0.0.1:8000/api/docs>。容器启动时会等待 PostgreSQL ready 并从空库执行 Alembic migration。

## 从公开信息添加基金

打开“数据运维”页，可使用两种主入口：

- 选择基金公司，再按来源分类和研究口径筛选并勾选基金；
- 输入六位基金代码，核对公开名称、基金公司和分类后确认导入。

只有显式选择的代码会写入本地数据库，原始公开响应会保存在本地 `.data/raw/catalog/` 并记录 URL、SHA-256 和 ingestion run。第三方目录可能延迟或变更，应以基金公司正式资料为准。

CSV、XLSX、JSON 作为高级批量或离线导入入口继续保留：

```bash
qdii validate-universe --file examples/universe.sample.csv
qdii import-universe --file examples/universe.sample.csv
```

示例仅含 synthetic 数据，不是完整名单、官方投资池或投资建议。字段定义和别名见 [docs/data-model.md](docs/data-model.md)。

## 同步与解析最新季度

```bash
qdii sync-reports --latest-quarter
qdii parse-reports --latest-quarter
qdii sync-daily
qdii coverage --latest-quarter
```

也可显式使用 `--year 2025 --quarter 4`。分析起点总是 `report.period_end + 1 day`，不固定到某个历史日期。

## 查看基金暴露与对比

导入并解析后，在基金详情页查看 direct/look-through 国家、行业、股票和基金持仓；“基金对比”页展示暴露差异、前十大重叠、净值走势与相关性。

## 运行披露持仓一致性分析

先把 `config/fund-analysis-proxies.example.yaml` 复制为 ignored 的 `.local.yaml`，配置用户有权使用的估算收益序列：

```bash
qdii analyze-fund --fund-code 123456 --latest-report
# 或
qdii analyze-fund --fund-code 123456 --year 2025 --quarter 4 --export-mode REDACTED
```

模型不会把前十大归一化为 100%，未披露仓位和 unresolved 基金权重保持独立；没有可靠代理时返回 `INSUFFICIENT_DATA`。

## Portfolio 隐私

Portfolio 默认关闭（`QDII_ENABLE_PORTFOLIO=false`）：不显示导航、不注册写入 CLI 或敏感 API、不读取 portfolio 文件。显式开启后只读取 `.data/private/portfolio.json`，不会自动上传，也不连接真实账户。Evidence 默认 `REDACTED`，且核心分析导出不包含平台名、内部 ID、现金流备注或用户私密字段。详见 [docs/portfolio-privacy.md](docs/portfolio-privacy.md)。

## 本地开发与检查

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
corepack enable
cd frontend && pnpm install --frozen-lockfile && cd ..
make dev-backend       # 终端 1
make dev-frontend      # 终端 2
make check
```

常用运维命令包括 `qdii init`、`qdii doctor`、`qdii backup`、`qdii restore --file ... --confirm`，以及 `make docker-up`、`make docker-restart`、`make docker-daily`、`make docker-down`、`make migrate`。`docker compose down` 不删除 volume。电脑开机后的启动、每日维护、停止、重启和代码更新步骤见 [docs/daily-operations.md](docs/daily-operations.md)。

## 文档入口

- [快速开始](docs/quickstart.md) · [配置](docs/configuration.md) · [架构](docs/architecture.md)
- [报告解析](docs/report-parsing.md) · [穿透](docs/lookthrough.md) · [披露持仓一致性](docs/disclosed-holdings-analysis.md)
- [数据来源](docs/data-sources.md) · [每日维护与重启](docs/daily-operations.md) · [运维/备份](docs/operations.md) · [故障排查](docs/troubleshooting.md)
- [贡献指南](CONTRIBUTING.md) · [安全](SECURITY.md) · [公开发布清单](PUBLIC_RELEASE_CHECKLIST.md)

## License

代码采用 Apache License 2.0。第三方数据、报告、接口响应与 PDF 的权利边界另见 [DATA_LICENSE.md](DATA_LICENSE.md)。
