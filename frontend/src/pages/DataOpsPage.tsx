import { useMutation, useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Database,
  Download,
  ExternalLink,
  FileWarning,
  Gauge,
  History,
  Plus,
  Play,
  RefreshCw,
  Search,
  ServerCog,
  ShieldAlert,
  WalletCards,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type {
  DataOperationName,
  DataOperationResult,
  DataPreparationStatus,
  DataQualityIssue,
  FundSummary,
  IngestionRun,
  PublicFundCandidate,
} from '../api/types'
import { EmptyPanel, ErrorPanel, LoadingPanel } from '../components/StatePanel'
import { StatusBadge } from '../components/StatusBadge'
import {
  displayText,
  field,
  formatConfidence,
  formatDate,
  issueTone,
  statusLabel,
  toNumber,
} from '../lib/format'

function isParsed(fund: FundSummary): boolean {
  return ['parsed', 'valid_empty'].includes(String(field(fund, 'latest_report_status', 'report_status', 'q2_report_status')).toLowerCase())
}

function isFailed(fund: FundSummary): boolean {
  return String(field(fund, 'latest_report_status', 'report_status', 'q2_report_status')).toLowerCase().includes('fail')
}

function issueMatches(issue: DataQualityIssue, words: string[]): boolean {
  const haystack = `${issue.issue_code ?? issue.issue_type ?? ''} ${issue.message ?? ''}`.toLowerCase()
  return words.some((word) => haystack.includes(word))
}

const issuePresentation: Record<string, { label: string; guidance: string }> = {
  REPORT_PARSE_FAILED: { label: '报告解析失败', guidance: '打开来源报告核对文件内容；修复解析规则或源文件后重新解析。' },
  REPORT_SOURCE_MISSING: { label: '缺少可解析的报告文件', guidance: '先重新获取报告；若公开页面已有文件，可通过来源链接核对。' },
  REPORT_SYNC_FAILED: { label: '报告获取失败', guidance: '检查公开来源是否可访问，然后重试报告同步。' },
  REPORT_NOT_DISCOVERED: { label: '未发现对应季度报告', guidance: '确认报告是否已公开，或通过基金详情中的来源页面人工核对。' },
  MULTIPLE_REPORT_CANDIDATES: { label: '发现多个候选报告', guidance: '通过来源链接核对报告期和基金身份，系统不会静默猜测。' },
  LOW_PARSE_CONFIDENCE: { label: '报告解析置信度偏低', guidance: '结果可查看但不应直接作为高置信度结论，请核对原始报告。' },
  NEGATIVE_PERCENTAGE: { label: '解析到负百分比', guidance: '核对表格列对齐、负号和 OCR 结果。' },
  TOP_HOLDINGS_EXCEED_EQUITY: { label: '前十大持仓超过权益占比', guidance: '持仓合计与资产配置不一致，需要核对原始表格。' },
  FUND_INVESTMENT_RECONCILIATION: { label: '基金投资占比勾稽不一致', guidance: '核对基金持仓和资产配置口径，暂不视为可靠穿透结果。' },
  EMPTY_WITHOUT_EXPLICIT_DISCLOSURE: { label: '解析为空且报告未明确披露为空', guidance: '可能是版式未识别，请打开来源报告检查对应章节。' },
  SALES_LIMIT_SYNC_FAILED: { label: '限额抓取失败', guidance: '查看具体份额和来源；公开页面恢复或份额归并修正后可重试同步。' },
  SALES_LIMIT_COVERAGE_INCOMPLETE: { label: '渠道覆盖不完整', guidance: '这表示缺少渠道或状态仍未知，不等同于暂停申购。' },
  SALES_LIMIT_CHANNEL_SCOPE_AMBIGUOUS: { label: '限额适用份额不明确', guidance: '公告未明确限额对应哪个份额，需通过来源人工核对。' },
}

const reportIssueCodes = new Set([
  'REPORT_PARSE_FAILED',
  'REPORT_SOURCE_MISSING',
  'REPORT_SYNC_FAILED',
  'REPORT_NOT_DISCOVERED',
  'MULTIPLE_REPORT_CANDIDATES',
  'LOW_PARSE_CONFIDENCE',
  'NEGATIVE_PERCENTAGE',
  'TOP_HOLDINGS_EXCEED_EQUITY',
  'FUND_INVESTMENT_RECONCILIATION',
  'EMPTY_WITHOUT_EXPLICIT_DISCLOSURE',
])

function normalizedIssueCode(issue: DataQualityIssue): string {
  return String(issue.issue_code ?? issue.issue_type ?? 'DATA_QUALITY_ISSUE')
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '_')
}

function isReportIssue(issue: DataQualityIssue): boolean {
  return reportIssueCodes.has(normalizedIssueCode(issue))
    || issueMatches(issue, ['report', 'parse', '报告', '解析', 'confidence', '置信度'])
}

function safeIssueSourceUrls(issue: DataQualityIssue): string[] {
  return [...new Set(issue.source_urls ?? [])].filter((value) => {
    try {
      return ['http:', 'https:'].includes(new URL(value).protocol)
    } catch {
      return false
    }
  })
}

const limitAvailabilityStates = [
  ['OPEN', '开放', 'success'],
  ['PAUSED', '暂停', 'failed'],
  ['UNKNOWN', '可售状态未知', 'warning'],
  ['NOT_SOLD', '该渠道未销售', 'neutral'],
  ['NOT_APPLICABLE', '不适用', 'neutral'],
] as const

const limitCapStates = [
  ['LIMITED', '有限额', 'warning'],
  ['UNLIMITED', '不限额', 'success'],
  ['UNKNOWN', '限额未知', 'neutral'],
] as const

export function DataOpsPage() {
  const runsQuery = useQuery({
    queryKey: ['ingestion-runs'],
    queryFn: ({ signal }) => api.ingestionRuns(signal),
    refetchInterval: 30_000,
  })
  const issuesQuery = useQuery({
    queryKey: ['data-quality-issues'],
    queryFn: ({ signal }) => api.dataQualityIssues(signal),
    refetchInterval: 30_000,
  })
  const fundsQuery = useQuery({
    queryKey: ['funds'],
    queryFn: ({ signal }) => api.funds(signal),
    refetchInterval: 30_000,
  })
  const limitCoverageQuery = useQuery({
    queryKey: ['purchase-limit-coverage'],
    queryFn: ({ signal }) => api.purchaseLimitCoverage(signal),
    refetchInterval: 30_000,
  })
  const providerHealthQuery = useQuery({
    queryKey: ['provider-health'],
    queryFn: ({ signal }) => api.providerHealth(signal),
    refetchInterval: 30_000,
  })
  const preparationQuery = useQuery({
    queryKey: ['data-preparation-status'],
    queryFn: ({ signal }) => api.dataPreparationStatus(signal),
    refetchInterval: (query) => {
      const status = query.state.data?.latest_operation?.status
      return status === 'queued' || status === 'running' ? 2_000 : 30_000
    },
  })
  const operationMutation = useMutation({
    mutationFn: ({ operation, fundCodes = [] }: {
      operation: DataOperationName
      fundCodes?: string[]
    }) => api.runDataOperation(operation, fundCodes),
    onSuccess: () => refreshAll(),
  })

  const funds = fundsQuery.data ?? []
  const persistedOperation = preparationQuery.data?.latest_operation
  const submittedOperation = operationMutation.data
  const operation = submittedOperation
    && (!persistedOperation || submittedOperation.id > persistedOperation.id)
    ? submittedOperation
    : persistedOperation
  const operationBusy = operationMutation.isPending
    || operation?.status === 'queued'
    || operation?.status === 'running'
  const runs = [...(runsQuery.data ?? [])].sort((a, b) => String(b.started_at ?? '').localeCompare(String(a.started_at ?? '')))
  const issues = [...(issuesQuery.data ?? [])].sort((a, b) => String(b.detected_at ?? b.created_at ?? '').localeCompare(String(a.detected_at ?? a.created_at ?? '')))
  const parsedCount = funds.filter(isParsed).length
  const failedFunds = funds.filter(isFailed)
  const coveragePct = funds.length ? parsedCount / funds.length * 100 : null
  const openIssues = issues.filter((issue) => !['resolved', 'closed'].includes(String(issue.status).toLowerCase()))
  const lowConfidenceIssues = openIssues.filter((issue) => issueMatches(issue, ['confidence', '置信度', 'low_confidence']))
  const navIssues = openIssues.filter((issue) => issueMatches(issue, ['nav', '净值', 'missing date', '缺失日期']))
  const limitIssues = openIssues.filter((issue) => issueMatches(issue, ['sales_limit', 'purchase_limit', '限额', '渠道']))
  const limitCoverage = limitCoverageQuery.data
  const limitCoveragePct = limitCoverage && limitCoverage.total_shares > 0
    ? limitCoverage.covered_shares / limitCoverage.total_shares * 100
    : null
  const lastRun = runs[0]
  const anyPending = fundsQuery.isPending || runsQuery.isPending || issuesQuery.isPending
    || limitCoverageQuery.isPending || providerHealthQuery.isPending || preparationQuery.isPending
    || operationMutation.isPending

  function refreshAll() {
    void Promise.all([
      fundsQuery.refetch(),
      runsQuery.refetch(),
      issuesQuery.refetch(),
      limitCoverageQuery.refetch(),
      providerHealthQuery.refetch(),
      preparationQuery.refetch(),
    ])
  }

  function runOperation(operation: DataOperationName, fundCodes: string[] = []) {
    operationMutation.mutate({ operation, fundCodes })
  }

  return (
    <div className="page-stack ops-page">
      <section className="page-intro ops-intro">
        <div>
          <span className="eyebrow"><ServerCog size={14} />DATA OPERATIONS</span>
          <h1>数据运维</h1>
          <p>每一次发现、下载、解析、净值与渠道限额同步都留下状态。失败与低置信度结果在这里显式暴露，不做静默回退。</p>
        </div>
        <button className="button button-secondary" type="button" onClick={refreshAll} disabled={anyPending}>
          <RefreshCw size={16} className={anyPending ? 'spin' : ''} />刷新状态
        </button>
      </section>

      <CatalogImportPanel onImported={refreshAll} />

      <DataPreparationPanel
        status={preparationQuery.data}
        pending={preparationQuery.isPending}
        error={preparationQuery.error}
        operationBusy={operationBusy}
        operation={operation}
        operationError={operationMutation.error}
        onRefresh={() => preparationQuery.refetch()}
        onRun={runOperation}
      />

      <section className="ops-stat-grid" aria-label="数据运维摘要">
        <article className="ops-stat ops-stat-coverage">
          <div className="ring-meter" style={{ '--progress': `${coveragePct ?? 0}%` } as CSSProperties}>
            <strong>{coveragePct === null ? '—' : `${Math.round(coveragePct)}%`}</strong>
          </div>
          <div><span>最新报告覆盖</span><strong>{fundsQuery.isSuccess ? `${parsedCount} / ${funds.length}` : '—'}</strong><small>已解析或明确有效空表</small></div>
        </article>
        <article className="ops-stat">
          <History size={21} />
          <div><span>最近任务</span><strong>{lastRun ? statusLabel(lastRun.status) : '暂无记录'}</strong><small>{lastRun ? formatDate(lastRun.started_at, true) : 'ingestion_run 未返回记录'}</small></div>
        </article>
        <article className="ops-stat">
          <FileWarning size={21} />
          <div><span>失败报告</span><strong>{fundsQuery.isSuccess ? failedFunds.length : '—'}</strong><small>每只均应保留失败原因</small></div>
        </article>
        <article className="ops-stat">
          <ShieldAlert size={21} />
          <div><span>开放质量问题</span><strong>{issuesQuery.isSuccess ? openIssues.length : '—'}</strong><small>其中低置信度 {issuesQuery.isSuccess ? lowConfidenceIssues.length : '—'} 项</small></div>
        </article>
      </section>

      <div className="detail-grid detail-grid-sidebar ops-grid">
        <section className="panel" aria-labelledby="runs-title">
          <div className="panel-heading">
            <div><span className="section-kicker">RUN HISTORY</span><h2 id="runs-title">最近 ingestion run</h2></div>
            <Clock3 size={20} />
          </div>
          {runsQuery.isPending && <LoadingPanel label="载入任务记录…" />}
          {runsQuery.isError && <ErrorPanel compact error={runsQuery.error} onRetry={() => runsQuery.refetch()} />}
          {runsQuery.isSuccess && runs.length === 0 && <EmptyPanel compact title="尚无执行记录" detail="运行导入或同步命令后，状态会显示在这里。" />}
          {runsQuery.isSuccess && runs.length > 0 && (
            <div className="run-list">
              {runs.slice(0, 10).map((run) => <RunRow key={String(run.id)} run={run} />)}
            </div>
          )}
        </section>

        <section className="panel" aria-labelledby="health-title">
          <div className="panel-heading">
            <div><span className="section-kicker">HEALTH</span><h2 id="health-title">需要关注</h2></div>
            <Gauge size={20} />
          </div>
          {issuesQuery.isPending && <LoadingPanel label="检查数据健康度…" />}
          {issuesQuery.isError && <ErrorPanel compact error={issuesQuery.error} onRetry={() => issuesQuery.refetch()} />}
          {issuesQuery.isSuccess && openIssues.length === 0 && <EmptyPanel compact title="没有开放问题" detail="问题表当前没有 open 状态记录。" />}
          {issuesQuery.isSuccess && openIssues.length > 0 && (
            <div className="health-stack">
              <div><span className="health-icon health-bad"><AlertCircle size={16} /></span><p><strong>{openIssues.filter((issue) => ['high', 'critical'].includes(String(issue.severity).toLowerCase())).length}</strong> 个高严重度问题</p></div>
              <div><span className="health-icon health-warn"><ShieldAlert size={16} /></span><p><strong>{lowConfidenceIssues.length}</strong> 个低置信度解析问题</p></div>
              <div><span className="health-icon health-neutral"><Database size={16} /></span><p><strong>{navIssues.length}</strong> 个净值缺失或异常问题</p></div>
              <div><span className="health-icon health-neutral"><WalletCards size={16} /></span><p><strong>{limitIssues.length}</strong> 个限额抓取或渠道覆盖问题</p></div>
            </div>
          )}
        </section>
      </div>

      <section className="panel" aria-labelledby="provider-health-title">
        <div className="panel-heading">
          <div><span className="section-kicker">PROVIDER HEALTH</span><h2 id="provider-health-title">数据来源状态</h2><p>未执行真实请求时保持 UNKNOWN，不把配置存在误报为健康。</p></div>
          <ServerCog size={20} />
        </div>
        {providerHealthQuery.isPending && <LoadingPanel label="载入 Provider 状态…" />}
        {providerHealthQuery.isError && <ErrorPanel compact error={providerHealthQuery.error} onRetry={() => providerHealthQuery.refetch()} />}
        {providerHealthQuery.isSuccess && providerHealthQuery.data.length === 0 && <EmptyPanel compact title="没有 Provider 配置" detail="复制并编辑 config/providers.example.yaml。" />}
        {providerHealthQuery.isSuccess && providerHealthQuery.data.length > 0 && (
          <div className="provider-health-list">
            {providerHealthQuery.data.map((provider) => (
              <div className="provider-health-row" key={provider.name}>
                <div className="provider-health-copy"><strong>{provider.name}</strong><small>优先级 {provider.priority}</small></div>
                <StatusBadge value={provider.status.toLowerCase()} label={provider.status} />
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel purchase-limit-coverage" aria-labelledby="limit-coverage-title">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">DAILY SALES LIMIT COVERAGE</span>
            <h2 id="limit-coverage-title">每日直销 / 代销限额覆盖</h2>
            <p>仅统计全局最新快照日；历史旧记录不会被算作今日覆盖。</p>
          </div>
          <WalletCards size={20} />
        </div>
        {limitCoverageQuery.isPending && <LoadingPanel label="计算最新限额快照覆盖…" />}
        {limitCoverageQuery.isError && <ErrorPanel compact error={limitCoverageQuery.error} onRetry={() => limitCoverageQuery.refetch()} />}
        {limitCoverageQuery.isSuccess && limitCoverage && (
          <>
            <div className="limit-coverage-grid">
              <div className="limit-coverage-primary">
                <div className="ring-meter" style={{ '--progress': `${limitCoveragePct ?? 0}%` } as CSSProperties}>
                  <strong>{limitCoveragePct === null ? '—' : `${Math.round(limitCoveragePct)}%`}</strong>
                </div>
                <div><span>份额覆盖</span><strong>{limitCoverage.covered_shares} / {limitCoverage.total_shares}</strong><small>基金覆盖 {limitCoverage.covered_funds} / {limitCoverage.total_funds}</small></div>
              </div>
              <div className="limit-snapshot-card">
                <span>最新快照日</span>
                <strong>{formatDate(limitCoverage.latest_snapshot_date)}</strong>
                <small>每日留档，不沿用旧日状态填充</small>
              </div>
              <div className="limit-state-group">
                <span>渠道可售状态</span>
                <div>{limitAvailabilityStates.map(([state, label, tone]) => (
                  <span key={state}><StatusBadge value={tone} label={label} /><strong>{limitCoverage.availability_state_counts[state] ?? 0}</strong></span>
                ))}</div>
              </div>
              <div className="limit-state-group">
                <span>金额上限状态</span>
                <div>{limitCapStates.map(([state, label, tone]) => (
                  <span key={state}><StatusBadge value={tone} label={label} /><strong>{limitCoverage.cap_state_counts[state] ?? 0}</strong></span>
                ))}</div>
              </div>
            </div>
            <p className="panel-note">状态计数按来源级记录统计，可能多于份额数；“开放”不等于“不限额”，“可售状态未知”也不等于“暂停”。</p>
          </>
        )}
      </section>

      <section className="panel" aria-labelledby="coverage-title">
        <div className="panel-heading">
          <div><span className="section-kicker">UNIVERSE COVERAGE</span><h2 id="coverage-title">基金覆盖情况</h2><p>用户导入 universe 的每一只基金都必须有明确状态。</p></div>
          <span className="panel-caption">{funds.length} 只已返回</span>
        </div>
        {fundsQuery.isPending && <LoadingPanel label="载入覆盖清单…" />}
        {fundsQuery.isError && <ErrorPanel error={fundsQuery.error} onRetry={() => fundsQuery.refetch()} />}
        {fundsQuery.isSuccess && funds.length === 0 && <EmptyPanel title="覆盖清单为空" detail="请先从公开信息选择基金、输入基金代码，或使用高级批量模板导入。" />}
        {fundsQuery.isSuccess && funds.length > 0 && (
          <div className="data-table-wrap">
            <table className="data-table coverage-table">
              <thead><tr><th>基金</th><th>报告状态</th><th>解析置信度</th><th>股票持仓</th><th>基金持仓</th><th>穿透状态</th><th>最新净值</th><th>单基金任务</th></tr></thead>
              <tbody>{funds.map((fund) => (
                <tr key={String(fund.id ?? fund.representative_code)}>
                  <td><Link className="fund-identity" to={`/funds/${encodeURIComponent(String(fund.id))}`}><strong>{fund.canonical_name}</strong><span><code>{fund.representative_code}</code>{fund.manager_name}</span></Link></td>
                  <td><StatusBadge value={field(fund, 'latest_report_status', 'report_status', 'q2_report_status')} /></td>
                  <td>{formatConfidence(field(fund, 'parse_confidence'))}</td>
                  <td>{displayText(field(fund, 'stock_holding_count'), '—')}</td>
                  <td>{displayText(field(fund, 'fund_holding_count'), '—')}</td>
                  <td><StatusBadge value={field(fund, 'lookthrough_status')} /></td>
                  <td>{formatDate(field(fund, 'latest_nav_date'))}</td>
                  <td>
                    <button
                      className="button button-quiet"
                      type="button"
                      disabled={operationBusy}
                      title="同步该基金的日常数据、最近季度报告并重新计算穿透"
                      onClick={() => runOperation('prepare', [fund.representative_code])}
                    >
                      <Play size={14} />补齐数据
                    </button>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <div className="operation-note">
          <ServerCog size={17} />
          <p><strong>“补齐数据”只处理这一只已导入基金。</strong> 它会同步近 10 天日常数据、获取最近已结束季度报告并重新解析穿透；所有结果仍记录在 ingestion run 中。</p>
        </div>
      </section>

      <div className="detail-grid ops-issue-grid">
        <IssuePanel title="失败与低置信度解析" kicker="REPORT ISSUES" issues={openIssues.filter(isReportIssue)} pending={issuesQuery.isPending} error={issuesQuery.error} onRetry={() => issuesQuery.refetch()} />
        <IssuePanel title="净值缺失日期" kicker="NAV GAPS" issues={navIssues} pending={issuesQuery.isPending} error={issuesQuery.error} onRetry={() => issuesQuery.refetch()} />
        <IssuePanel title="限额抓取与渠道覆盖" kicker="SALES LIMIT ISSUES" issues={limitIssues} pending={issuesQuery.isPending} error={issuesQuery.error} onRetry={() => issuesQuery.refetch()} />
      </div>
    </div>
  )
}

function DataPreparationPanel({
  status,
  pending,
  error,
  operationBusy,
  operation,
  operationError,
  onRefresh,
  onRun,
}: {
  status: DataPreparationStatus | undefined
  pending: boolean
  error: unknown
  operationBusy: boolean
  operation: DataOperationResult | null | undefined
  operationError: unknown
  onRefresh: () => void
  onRun: (operation: DataOperationName, fundCodes?: string[]) => void
}) {
  if (pending) return <section className="panel"><LoadingPanel label="计算基金数据准备状态…" /></section>
  if (error) return <section className="panel"><ErrorPanel error={error} onRetry={onRefresh} /></section>
  if (!status) return null

  const total = status.total_funds
  const stages = [
    { key: 'funds', label: '基金清单', ready: total, detail: total ? `${status.total_shares} 个份额代码已归并` : '先导入基金' },
    { key: 'nav', label: '净值与价格', ready: status.nav_ready_funds, detail: status.latest_nav_date ? `最新 ${formatDate(status.latest_nav_date)}` : '尚未同步' },
    { key: 'limits', label: '今日申购限额', ready: status.limit_ready_funds, detail: status.latest_limit_snapshot_date ? `快照 ${formatDate(status.latest_limit_snapshot_date)}` : '尚无快照' },
    { key: 'reports', label: `${status.report_year} Q${status.report_quarter} 季报`, ready: status.report_downloaded_funds, detail: '最近已结束季度' },
    { key: 'parsed', label: '报告解析', ready: status.report_parsed_funds, detail: '国家、行业与披露持仓' },
    { key: 'lookthrough', label: '穿透计算', ready: status.lookthrough_ready_funds, detail: '不把未解析权重填成 0' },
  ]
  const fullyReady = total > 0 && stages.slice(1).every((stage) => stage.ready === total)
  const operationLabels: Record<DataOperationName, string> = {
    prepare: '准备全部数据',
    'sync-daily': '同步日常数据',
    'sync-sales-limits': '同步今日限额',
    'sync-reports': '获取季度报告',
    'parse-reports': '解析报告并计算穿透',
  }
  const operationActive = operation?.status === 'queued' || operation?.status === 'running'

  return (
    <section className="panel data-preparation" aria-labelledby="data-preparation-title">
      <div className="panel-heading data-preparation-heading">
        <div>
          <span className="section-kicker">NEXT STEPS</span>
          <h2 id="data-preparation-title">数据准备向导</h2>
          <p>{total > 0
            ? `已归并为 ${total} 个基金合同、${status.total_shares} 个份额。日常数据与季度报告可以独立同步；穿透需要先取得并解析报告。`
            : '导入基金后，这里会引导完成净值、限额、季报和穿透数据。'}</p>
        </div>
        {fullyReady && <StatusBadge value="success" label="基础数据已就绪" />}
      </div>

      <div className="preparation-stage-grid">
        {stages.map((stage) => {
          const complete = total > 0 && stage.ready === total
          return (
            <article className={complete ? 'preparation-stage is-complete' : 'preparation-stage'} key={stage.key}>
              {complete ? <CheckCircle2 size={18} /> : <CircleDashed size={18} />}
              <div><span>{stage.label}</span><strong>{stage.ready} / {total}</strong><small>{stage.detail}</small></div>
            </article>
          )
        })}
      </div>

      {total > 0 && (
        <div className="preparation-actions">
          <button className="button button-primary" type="button" disabled={operationBusy} onClick={() => onRun('prepare')}>
            <Play size={15} />{fullyReady ? `更新全部 ${total} 只基金数据` : `开始准备 ${total} 只基金数据`}
          </button>
          <button className="button button-secondary" type="button" disabled={operationBusy} onClick={() => onRun('sync-daily')}>
            同步日常数据
          </button>
          <button className="button button-secondary" type="button" disabled={operationBusy} onClick={() => onRun('sync-sales-limits')}>
            仅同步今日限额
          </button>
          <button className="button button-secondary" type="button" disabled={operationBusy} onClick={() => onRun('sync-reports')}>
            获取 {status.report_year} Q{status.report_quarter} 报告
          </button>
          <button className="button button-secondary" type="button" disabled={operationBusy || status.report_downloaded_funds === 0} onClick={() => onRun('parse-reports')}>
            解析报告并计算穿透
          </button>
        </div>
      )}

      {operationActive && operation && (
        <div className="preparation-running" role="status">
          <RefreshCw size={16} className="spin" />
          <div>
            <strong>
              任务 #{operation.id}：{statusLabel(operation.status)} · {operationLabels[operation.current_stage ?? operation.operation]}
            </strong>
            <span>阶段 {operation.stage_completed} / {operation.stage_total}；任务在独立 worker 运行，刷新页面不会丢失进度。</span>
          </div>
        </div>
      )}
      {Boolean(operationError) && <ErrorPanel compact error={operationError} />}
      {operation && !operationActive && (
        <div className={`preparation-result tone-${issueTone(operation.status)}`} role="status">
          <div>
            <strong>任务 #{operation.id} 已结束：{statusLabel(operation.status)}</strong>
            <span>{operation.fund_codes.length} 个基金合同 · 完成阶段 {operation.stage_completed} / {operation.stage_total} · {formatDate(operation.finished_at, true)}</span>
            {operation.status === 'partial' && <span>部分完成表示已有可用数据，但仍有失败项；未覆盖部分不会被伪装成完成，请查看下方任务记录和质量问题。</span>}
            {operation.error_message && <span>{operation.error_message}</span>}
          </div>
          <div><strong>{operation.records_written}</strong><span>写入</span><strong>{operation.records_failed}</strong><span>失败</span></div>
        </div>
      )}

      {total > 0 && (status.nav_ready_funds > 0 || status.report_parsed_funds > 0) && (
        <div className="preparation-links">
          <Link className="text-button" to="/">查看基金总览</Link>
          {Math.max(status.nav_ready_funds, status.report_parsed_funds) >= 2 && <Link className="text-button" to="/compare">选择基金进行对比</Link>}
        </div>
      )}
    </section>
  )
}

function CatalogImportPanel({ onImported }: { onImported: () => void }) {
  const [companyCode, setCompanyCode] = useState('')
  const [sourceCategory, setSourceCategory] = useState('ALL')
  const [researchScope, setResearchScope] = useState('ALL')
  const [selectedCodes, setSelectedCodes] = useState<Set<string>>(new Set())
  const [fundCode, setFundCode] = useState('')

  const optionsQuery = useQuery({
    queryKey: ['fund-catalog-options'],
    queryFn: ({ signal }) => api.fundCatalogOptions(signal),
    staleTime: 60 * 60 * 1000,
  })
  const hasCatalogFilter = Boolean(companyCode)
    || sourceCategory !== 'ALL'
    || researchScope !== 'ALL'
  const candidatesQuery = useQuery({
    queryKey: ['fund-catalog-candidates', companyCode, sourceCategory, researchScope],
    queryFn: ({ signal }) => api.fundCatalogCandidates({
      companyCode,
      sourceCategory,
      researchScope,
    }, signal),
    enabled: hasCatalogFilter,
    staleTime: 15 * 60 * 1000,
  })
  const lookupMutation = useMutation({
    mutationFn: (code: string) => api.lookupPublicFund(code),
  })
  const importMutation = useMutation({
    mutationFn: (codes: string[]) => api.importPublicFunds(codes),
    onSuccess: () => {
      setSelectedCodes(new Set())
      onImported()
    },
  })

  const candidates = useMemo(() => candidatesQuery.data?.items ?? [], [candidatesQuery.data])
  const allCandidatesSelected = candidates.length > 0
    && candidates.every((candidate) => selectedCodes.has(candidate.fund_code))

  function changeFilter(update: () => void) {
    update()
    setSelectedCodes(new Set())
  }

  function toggleCandidate(code: string) {
    setSelectedCodes((current) => {
      const next = new Set(current)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })
  }

  function toggleAllCandidates() {
    setSelectedCodes(
      allCandidatesSelected
        ? new Set()
        : new Set(candidates.map((candidate) => candidate.fund_code)),
    )
  }

  function lookupCode() {
    const normalized = fundCode.trim()
    if (/^[0-9]{6}$/.test(normalized)) lookupMutation.mutate(normalized)
  }

  return (
    <section className="catalog-import-grid" aria-labelledby="catalog-import-title">
      <div className="panel catalog-browser">
        <div className="panel-heading">
          <div>
            <span className="section-kicker">PUBLIC FUND CATALOG</span>
            <h2 id="catalog-import-title">从公开信息选择基金</h2>
            <p>基金公司、来源分类、研究口径可单独使用或任意组合；只有勾选的基金代码会写入本地 universe。</p>
          </div>
          <Database size={20} />
        </div>
        {optionsQuery.isPending && <LoadingPanel label="读取公开基金公司目录…" />}
        {optionsQuery.isError && <ErrorPanel compact error={optionsQuery.error} onRetry={() => optionsQuery.refetch()} />}
        {optionsQuery.isSuccess && (
          <>
            <div className="catalog-filter-grid">
              <label>
                <span>基金公司</span>
                <select value={companyCode} onChange={(event) => changeFilter(() => setCompanyCode(event.target.value))}>
                  <option value="">全部基金公司</option>
                  {optionsQuery.data.companies.map((company) => (
                    <option key={company.company_code} value={company.company_code}>{company.company_name}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>来源分类</span>
                <select value={sourceCategory} onChange={(event) => changeFilter(() => setSourceCategory(event.target.value))}>
                  {optionsQuery.data.source_categories.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>研究口径</span>
                <select value={researchScope} onChange={(event) => changeFilter(() => setResearchScope(event.target.value))}>
                  {optionsQuery.data.research_scopes.map((scope) => (
                    <option key={scope.value} value={scope.value}>{scope.label}</option>
                  ))}
                </select>
              </label>
            </div>
            <p className="panel-note">{optionsQuery.data.source_notice} “研究口径”按公开基金名称启发式匹配、按份额代码返回，不等于人工归并后的基金合同清单，也不是投资建议。</p>
          </>
        )}
        {!hasCatalogFilter && optionsQuery.isSuccess && <EmptyPanel compact title="请选择至少一个筛选条件" detail="基金公司、来源分类、研究口径均可作为第一个条件，也可以单独查询。" />}
        {hasCatalogFilter && candidatesQuery.isPending && <LoadingPanel label="读取公开 QDII 清单…" />}
        {candidatesQuery.isError && <ErrorPanel compact error={candidatesQuery.error} onRetry={() => candidatesQuery.refetch()} />}
        {candidatesQuery.isSuccess && candidates.length === 0 && <EmptyPanel compact title="当前筛选没有基金" detail="可更换来源分类或研究口径；不会用相似基金自动补位。" />}
        {candidatesQuery.isSuccess && candidates.length > 0 && (
          <>
            <div className="catalog-candidate-list">
              {candidates.map((candidate) => (
                <CatalogCandidateRow
                  key={candidate.fund_code}
                  candidate={candidate}
                  selected={selectedCodes.has(candidate.fund_code)}
                  onToggle={() => toggleCandidate(candidate.fund_code)}
                />
              ))}
            </div>
            <div className="catalog-actions">
              <div className="catalog-selection-controls">
                <span>已选择 <strong>{selectedCodes.size}</strong> / {candidates.length} 个份额代码</span>
                <button className="button button-secondary" type="button" onClick={toggleAllCandidates}>
                  {allCandidatesSelected ? '取消全选' : `全选当前 ${candidates.length} 个`}
                </button>
              </div>
              <button
                className="button button-primary"
                type="button"
                disabled={selectedCodes.size === 0 || importMutation.isPending}
                onClick={() => importMutation.mutate([...selectedCodes])}
              >
                <Plus size={15} />导入所选基金
              </button>
            </div>
          </>
        )}
      </div>

      <div className="catalog-side-stack">
        <div className="panel catalog-code-import">
          <div className="panel-heading">
            <div><span className="section-kicker">EXACT CODE</span><h2>按基金代码添加</h2><p>输入六位代码，先读取并核对公开资料，再确认导入。</p></div>
            <Search size={20} />
          </div>
          <label className="catalog-code-field">
            <span className="sr-only">六位基金代码</span>
            <input
              inputMode="numeric"
              maxLength={6}
              value={fundCode}
              onChange={(event) => setFundCode(event.target.value.replace(/\D/g, ''))}
              placeholder="例如：六位基金代码"
            />
            <button className="button button-secondary" type="button" disabled={fundCode.length !== 6 || lookupMutation.isPending} onClick={lookupCode}>查询</button>
          </label>
          {lookupMutation.isError && <ErrorPanel compact error={lookupMutation.error} />}
          {lookupMutation.data && (
            <div className="catalog-code-preview">
              <code>{lookupMutation.data.fund_code}</code>
              <strong>{lookupMutation.data.fund_name}</strong>
              <span>{lookupMutation.data.manager_name} · {lookupMutation.data.category}</span>
              <a href={lookupMutation.data.source_url} target="_blank" rel="noreferrer">查看公开来源</a>
              <button className="button button-primary" type="button" disabled={importMutation.isPending} onClick={() => importMutation.mutate([lookupMutation.data.fund_code])}><Plus size={15} />确认导入</button>
            </div>
          )}
        </div>

        <div className="panel catalog-advanced-import">
          <span className="section-kicker">ADVANCED IMPORT</span>
          <h2>批量文件导入</h2>
          <p>下载 XLSX 模板后，在“基金合同明细”中每行填写一个主基金合同；先校验，再执行导入。</p>
          <a className="button button-secondary catalog-template-download" href="/templates/universe-import-template.xlsx" download>
            <Download size={15} />下载 XLSX 模板
          </a>
          <code>qdii import-universe --file &lt;path&gt;</code>
        </div>

        {importMutation.isError && <ErrorPanel compact error={importMutation.error} />}
        {importMutation.data && (
          <div className={`catalog-import-result tone-${issueTone(importMutation.data.status)}`} role="status">
            <strong>导入状态：{statusLabel(importMutation.data.status)}</strong>
            <span>成功 {importMutation.data.imported_codes.length} 只，失败 {Object.keys(importMutation.data.failures).length} 只。</span>
          </div>
        )}
      </div>
    </section>
  )
}

function CatalogCandidateRow({ candidate, selected, onToggle }: {
  candidate: PublicFundCandidate
  selected: boolean
  onToggle: () => void
}) {
  return (
    <label className={selected ? 'catalog-candidate is-selected' : 'catalog-candidate'}>
      <input type="checkbox" checked={selected} onChange={onToggle} />
      <code>{candidate.fund_code}</code>
      <span><strong>{candidate.fund_name}</strong><small>{candidate.category} · {candidate.currency} · {candidate.wrapper_type}</small></span>
      <em>{candidate.research_scope}</em>
    </label>
  )
}

function RunRow({ run }: { run: IngestionRun }) {
  const total = toNumber(run.records_seen ?? run.discovered_count) ?? 0
  const success = toNumber(run.records_written ?? run.success_count) ?? 0
  const failed = toNumber(run.records_failed ?? run.failed_count) ?? 0
  const provider = run.provider_name
    ?? (typeof run.parameters?.provider === 'string' ? run.parameters.provider : null)
  const completion = total > 0
    ? Math.max(0, Math.min(100, (total - failed) / total * 100))
    : String(run.status).toLowerCase() === 'succeeded' ? 100 : 0
  return (
    <article className="run-row">
      <span className={`run-dot tone-${issueTone(run.status)}`} />
      <div className="run-copy">
        <div><strong>{displayText(run.job_type ?? run.run_type, '未命名任务')}</strong><StatusBadge value={run.status} /></div>
        <span>{displayText(provider, 'provider 未标注')} · {formatDate(run.started_at, true)}</span>
        {(run.error_message ?? run.error_summary) && <small>{run.error_message ?? run.error_summary}</small>}
        <div className="progress-track"><i style={{ width: `${completion}%` }} /></div>
      </div>
      <div className="run-count">
        <strong>{success}</strong><span>行</span>
        <small>{total || '—'} 个对象{failed > 0 ? ` · ${failed} 失败` : ''}</small>
      </div>
    </article>
  )
}

function IssuePanel({ title, kicker, issues, pending, error, onRetry }: {
  title: string
  kicker: string
  issues: DataQualityIssue[]
  pending: boolean
  error: unknown
  onRetry: () => void
}) {
  const groups = [...issues.reduce((result, issue) => {
    const code = normalizedIssueCode(issue)
    result.set(code, [...(result.get(code) ?? []), issue])
    return result
  }, new Map<string, DataQualityIssue[]>())]
    .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))

  return (
    <section className="panel">
      <div className="panel-heading"><div><span className="section-kicker">{kicker}</span><h2>{title}</h2></div><FileWarning size={20} /></div>
      {pending && <LoadingPanel label="载入质量问题…" />}
      {Boolean(error) && <ErrorPanel compact error={error} onRetry={onRetry} />}
      {!pending && !error && issues.length === 0 && <EmptyPanel compact title="没有相关问题" detail="当前问题表未返回这一类型的开放记录。" />}
      {!pending && !error && issues.length > 0 && (
        <div className="issue-groups">
          <p className="issue-group-hint">已按错误类型归组，点击一类查看基金、原始错误和溯源链接。</p>
          {groups.map(([code, group]) => {
            const presentation = issuePresentation[code] ?? {
              label: '其他数据质量问题',
              guidance: '请根据内部错误码、具体信息和来源记录进一步核对。',
            }
            const severity = group.some((issue) => issueTone(issue.severity) === 'bad') ? 'ERROR' : 'WARNING'
            return (
              <details className="issue-group" key={code}>
                <summary>
                  <span>{issueTone(severity) === 'bad' ? <AlertCircle size={17} /> : <ShieldAlert size={17} />}</span>
                  <span className="issue-group-title"><strong>{presentation.label}</strong><code>{code}</code></span>
                  <span className="issue-group-count">{group.length} 项</span>
                </summary>
                <p className="issue-guidance">{presentation.guidance}</p>
                <div className="issue-list ops-issue-list">
                  {group.map((issue) => {
                    const sourceUrls = safeIssueSourceUrls(issue)
                    return (
                      <article key={String(issue.id)}>
                        {issueTone(issue.severity) === 'bad' ? <AlertCircle size={17} /> : <ShieldAlert size={17} />}
                        <div>
                          <strong>{displayText(issue.fund_name ?? issue.representative_code ?? issue.fund_contract_id, '未关联基金')}</strong>
                          <p>{displayText(issue.message)}</p>
                          <small>
                            {issue.fund_contract_id ? <Link to={`/funds/${String(issue.fund_contract_id)}`}>{displayText(issue.representative_code, '查看基金')}</Link> : displayText(issue.representative_code, '未关联基金')}
                            {' · '}{formatDate(issue.detected_at ?? issue.created_at, true)}
                          </small>
                          {sourceUrls.length > 0 && (
                            <div className="issue-source-links">
                              {sourceUrls.map((url, index) => <a href={url} target="_blank" rel="noreferrer" key={url}><ExternalLink size={12} />来源 {index + 1}</a>)}
                            </div>
                          )}
                        </div>
                        <StatusBadge value={issue.severity} />
                      </article>
                    )
                  })}
                </div>
              </details>
            )
          })}
        </div>
      )}
    </section>
  )
}
