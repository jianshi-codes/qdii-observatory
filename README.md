# QDII Observatory（QDII 基金观察台）

一个面向中国内地 QDII 基金的本地优先研究工作台。它把基金清单、正式季报、每日净值、场内价格、申购限额和穿透结果放进同一条可追溯证据链。

![基金总览（合成数据）](docs/images/fund-overview-synthetic.png)

> 截图使用仓库内的 synthetic demo，不代表任何真实基金、账户或持仓。

## 能做什么

- 按基金公司、来源分类、研究领域或六位代码，从公开信息添加自选基金。
- 归档原始报告与来源链接，解析国家、行业、股票和基金持仓，并保留质量问题。
- 分开保存官方净值、场内价格、申购限额和汇率，支持基金详情与多基金对比。
- 为主动科技 QDII 的核心 18 只和广义 33 只基金池即时计算每日、MTD、QTD 收益，并按季度查看直接/穿透地区分布；两个看板都可导出固定尺寸 PNG。
- 默认提供本地持仓、定投确认和披露持仓一致性分析；不连接账户、不自动交易。
- 持仓一致性结果可生成身份脱敏的完整财务 JSON，预览后复制给 ChatGPT 做辅助研究。

项目不生成买卖指令，公开数据可能延迟或不完整，所有输出仅用于研究，不构成投资建议。详见 [免责声明](DISCLAIMER.md)。

## 持仓一致性与 AI 辅助研究

“持仓一致性”把用户持仓权重、季度披露、最新净值和估算涨跌放在同一张表中，展示逐基金偏差、累计偏差、解释覆盖和底层重叠，帮助判断静态季报对当前组合还有多少解释力。

![持仓一致性分析（合成数据）](docs/images/portfolio-consistency-synthetic.jpg)

分析完成后可预览并复制完整 JSON，或直接复制已经组织好的 ChatGPT 提示词。导出保留总资产、份额、收益、定投、现金流和备注，但删除平台名与本地数据库 ID；应用本身不会连接或上传到 AI 服务。

![AI 持仓分析导出（合成数据）](docs/images/portfolio-ai-export-synthetic.jpg)

> 两张截图均使用人工构造的基金、金额和分析结果，不包含真实账户或持仓。

## 5 分钟启动

需要 Git、Docker Engine（或 Docker Desktop）和 Docker Compose v2。

```bash
git clone <your-fork-or-local-repository-url> qdii-observatory
cd qdii-observatory
cp .env.example .env
# 修改 .env 中的示例数据库密码
docker compose up --build
```

打开 <http://127.0.0.1:5173>。API 文档位于 <http://127.0.0.1:8000/api/docs>，就绪检查位于 <http://127.0.0.1:8000/ready>。

第一次使用建议按下面的顺序：

1. 在“数据运维”中从公开信息选择基金，或输入六位基金代码。
2. 为新基金运行“按本季度补齐全部阶段”。
3. 在“基金总览”查看覆盖，在基金详情和“基金对比”查看暴露与净值。
4. 在“我的持仓”通过 XLSX 预览确认或手动录入；如不需要该模块，可设置 `QDII_ENABLE_PORTFOLIO=false` 后重启关闭。

逐页操作、状态解释和常见问题见 [用户指南](docs/user-guide.md)。外部 PostgreSQL、自动建库授权和冲突库保护见 [外部 PostgreSQL](docs/external-postgresql.md)。

## 数据与隐私边界

- 第三方原始数据默认只保存在本地 `.data/`，不随代码仓库分发。
- “我的持仓”默认开启，但初始为空；不会连接券商或自动上传文件，也可通过环境变量显式关闭。
- AI 分析导出会保留资产金额、份额、收益、定投、现金流和备注，只删除平台名及数据库 ID；粘贴到外部服务前应自行确认隐私边界。
- 不要提交 `.env`、数据库、备份、真实持仓、Provider 原始响应、cookie、token 或本地覆盖配置。
- Issue、日志和截图也应只使用 synthetic 数据。公开发布前请执行 [发布清单](PUBLIC_RELEASE_CHECKLIST.md)。

数据来源、许可和 Provider 边界见 [DATA_SOURCES.md](DATA_SOURCES.md) 与 [DATA_LICENSE.md](DATA_LICENSE.md)。

## 本地开发

宿主机开发需要 Python 3.12+、Node.js 22.22+ 和 pnpm 11；Docker 启动不需要这些宿主机运行时。

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
corepack enable
cd frontend && pnpm install --frozen-lockfile && cd ..
make dev-backend       # 终端 1
make dev-frontend      # 终端 2
make check
```

## 文档

- 上手与运维：[用户指南](docs/user-guide.md) · [快速开始](docs/quickstart.md) · [每日维护与重启](docs/daily-operations.md) · [故障排查](docs/troubleshooting.md)
- 部署与设计：[配置](docs/configuration.md) · [外部 PostgreSQL](docs/external-postgresql.md) · [架构](docs/architecture.md) · [数据模型](docs/data-model.md)
- 研究方法：[报告解析](docs/report-parsing.md) · [穿透](docs/lookthrough.md) · [披露持仓一致性](docs/disclosed-holdings-analysis.md)
- 专题看板：[主动科技 QDII 看板](docs/active-tech-dashboards.md)
- 项目治理：[贡献指南](CONTRIBUTING.md) · [隐私](PRIVACY.md) · [安全](SECURITY.md) · [变更记录](CHANGELOG.md) · [路线图](ROADMAP.md)

## License

代码采用 Apache License 2.0。第三方数据、报告、接口响应与 PDF 不自动受该许可证覆盖。
