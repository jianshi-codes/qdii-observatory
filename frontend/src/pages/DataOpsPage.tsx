import { useMutation, useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  Clock3,
  Database,
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

  const funds = fundsQuery.data ?? []
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
  const anyPending = fundsQuery.isPending || runsQuery.isPending || issuesQuery.isPending || limitCoverageQuery.isPending || providerHealthQuery.isPending

  function refreshAll() {
    void Promise.all([
      fundsQuery.refetch(),
      runsQuery.refetch(),
      issuesQuery.refetch(),
      limitCoverageQuery.refetch(),
      providerHealthQuery.refetch(),
    ])
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
          <div className="run-list">
            {providerHealthQuery.data.map((provider) => (
              <div className="run-row" key={provider.name}>
                <div><strong>{provider.name}</strong><small>priority {provider.priority}</small></div>
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
        {fundsQuery.isSuccess && funds.length === 0 && <EmptyPanel title="覆盖清单为空" detail="尚未导入 CSV、XLSX 或 JSON universe；不会用占位数据伪造覆盖。" />}
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
                      disabled
                      title="当前最小 API 未定义写操作；请使用后端单基金 CLI 重跑"
                    >
                      <Play size={14} />重跑
                    </button>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <div className="operation-note">
          <ServerCog size={17} />
          <p><strong>重跑操作尚未由只读 MVP API 暴露。</strong> 为避免猜测写接口，按钮保持禁用；可使用后端 CLI 按基金执行，待明确重跑端点后再接通。</p>
        </div>
      </section>

      <div className="detail-grid ops-issue-grid">
        <IssuePanel title="失败与低置信度解析" kicker="REPORT ISSUES" issues={openIssues.filter((issue) => issueMatches(issue, ['report', 'parse', '报告', '解析', 'confidence', '置信度']))} pending={issuesQuery.isPending} error={issuesQuery.error} onRetry={() => issuesQuery.refetch()} />
        <IssuePanel title="净值缺失日期" kicker="NAV GAPS" issues={navIssues} pending={issuesQuery.isPending} error={issuesQuery.error} onRetry={() => issuesQuery.refetch()} />
        <IssuePanel title="限额抓取与渠道覆盖" kicker="SALES LIMIT ISSUES" issues={limitIssues} pending={issuesQuery.isPending} error={issuesQuery.error} onRetry={() => issuesQuery.refetch()} />
      </div>
    </div>
  )
}

function CatalogImportPanel({ onImported }: { onImported: () => void }) {
  const [companyCode, setCompanyCode] = useState('')
  const [category, setCategory] = useState('ALL')
  const [researchScope, setResearchScope] = useState('ALL')
  const [selectedCodes, setSelectedCodes] = useState<Set<string>>(new Set())
  const [fundCode, setFundCode] = useState('')

  const optionsQuery = useQuery({
    queryKey: ['fund-catalog-options'],
    queryFn: ({ signal }) => api.fundCatalogOptions(signal),
    staleTime: 60 * 60 * 1000,
  })
  const candidatesQuery = useQuery({
    queryKey: ['fund-catalog-candidates', companyCode],
    queryFn: ({ signal }) => api.fundCatalogCandidates(companyCode, signal),
    enabled: Boolean(companyCode),
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

  const candidates = useMemo(() => {
    const rows = candidatesQuery.data?.items ?? []
    return rows.filter((item) => (
      (category === 'ALL' || item.category === category)
      && (researchScope === 'ALL' || item.research_scope === researchScope)
    ))
  }, [candidatesQuery.data, category, researchScope])

  function changeCompany(value: string) {
    setCompanyCode(value)
    setCategory('ALL')
    setResearchScope('ALL')
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
            <p>先选基金公司，再按来源分类和研究口径筛选；只有勾选的基金代码会写入本地 universe。</p>
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
                <select value={companyCode} onChange={(event) => changeCompany(event.target.value)}>
                  <option value="">请选择基金公司</option>
                  {optionsQuery.data.companies.map((company) => (
                    <option key={company.company_code} value={company.company_code}>{company.company_name}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>来源分类</span>
                <select value={category} onChange={(event) => setCategory(event.target.value)} disabled={!candidatesQuery.data}>
                  <option value="ALL">全部分类</option>
                  {(candidatesQuery.data?.categories ?? []).map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
              <label>
                <span>研究口径</span>
                <select value={researchScope} onChange={(event) => setResearchScope(event.target.value)}>
                  {optionsQuery.data.research_scopes.map((scope) => (
                    <option key={scope.value} value={scope.value}>{scope.label}</option>
                  ))}
                </select>
              </label>
            </div>
            <p className="panel-note">{optionsQuery.data.source_notice} “研究口径”是本项目的名称规则筛选，不是来源方分类或投资建议。</p>
          </>
        )}
        {candidatesQuery.isPending && <LoadingPanel label="读取该基金公司的 QDII 清单…" />}
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
              <span>已选择 <strong>{selectedCodes.size}</strong> 只</span>
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
          <p>CSV、XLSX、JSON 继续保留给自定义字段、离线目录或大批量迁移，不再是新用户的首要入口。</p>
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
  return (
    <section className="panel">
      <div className="panel-heading"><div><span className="section-kicker">{kicker}</span><h2>{title}</h2></div><FileWarning size={20} /></div>
      {pending && <LoadingPanel label="载入质量问题…" />}
      {Boolean(error) && <ErrorPanel compact error={error} onRetry={onRetry} />}
      {!pending && !error && issues.length === 0 && <EmptyPanel compact title="没有相关问题" detail="当前问题表未返回这一类型的开放记录。" />}
      {!pending && !error && issues.length > 0 && (
        <div className="issue-list ops-issue-list">
          {issues.slice(0, 12).map((issue) => (
            <article key={String(issue.id)}>
              {issueTone(issue.severity) === 'bad' ? <AlertCircle size={17} /> : <ShieldAlert size={17} />}
              <div>
                <strong>{displayText(issue.issue_code ?? issue.issue_type, '数据质量问题')}</strong>
                <p>{displayText(issue.message)}</p>
                <small>{displayText(issue.representative_code ?? issue.fund_name ?? issue.fund_contract_id, '未关联基金')} · {formatDate(issue.detected_at ?? issue.created_at, true)}</small>
              </div>
              <StatusBadge value={issue.severity} />
            </article>
          ))}
        </div>
      )}
      {issues.length > 12 && <p className="panel-note">仅显示最近 12 项，共 {issues.length} 项。</p>}
    </section>
  )
}
