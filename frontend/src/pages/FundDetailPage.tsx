import { useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import {
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  Boxes,
  CalendarDays,
  ExternalLink,
  FileText,
  Gauge,
  GitBranch,
  Globe2,
  Landmark,
  LineChart,
  Network,
  PieChart,
  ShieldCheck,
  WalletCards,
} from 'lucide-react'
import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type {
  ExposureItem,
  FundHolding,
  FundRelation,
  NavPoint,
  PurchaseLimit,
  PurchaseLimitAvailabilityState,
  PurchaseLimitCapState,
  SecurityHolding,
} from '../api/types'
import { EChart } from '../components/EChart'
import { MetricCard } from '../components/MetricCard'
import { EmptyPanel, ErrorPanel, LoadingPanel } from '../components/StatePanel'
import { StatusBadge } from '../components/StatusBadge'
import {
  displayText,
  field,
  formatConfidence,
  formatDate,
  formatMoney,
  formatPercent,
  relationTypeLabel,
  reportTypeLabel,
  statusLabel,
  techScopeLabel,
  toNumber,
  wrapperLabel,
} from '../lib/format'

interface ExposureRow {
  name: string
  direct: number | null
  lookthrough: number | null
}

function exposureName(item: ExposureItem): string {
  return displayText(
    item.country_normalized
      ?? item.industry_normalized
      ?? item.name_normalized
      ?? item.normalized_name
      ?? item.name
      ?? item.label
      ?? item.name_raw
      ?? item.raw_name,
    '未归一化',
  )
}

function exposureRows(items: ExposureItem[]): ExposureRow[] {
  const rows = new Map<string, ExposureRow>()
  for (const item of items) {
    const name = exposureName(item)
    const current = rows.get(name) ?? { name, direct: null, lookthrough: null }
    const scope = String(item.exposure_scope ?? field(item, 'scope', 'exposure_type')).toLowerCase()
    const navPct = toNumber(item.nav_pct)
    const direct = toNumber(item.direct_nav_pct)
    const lookthrough = toNumber(item.lookthrough_nav_pct)

    if (direct !== null) current.direct = direct
    if (lookthrough !== null) current.lookthrough = lookthrough
    if (navPct !== null && scope.includes('look')) current.lookthrough = navPct
    if (navPct !== null && !scope.includes('look')) current.direct = navPct
    rows.set(name, current)
  }
  return [...rows.values()]
    .filter((row) => row.direct !== null || row.lookthrough !== null)
    .sort((a, b) => Math.max(b.direct ?? 0, b.lookthrough ?? 0) - Math.max(a.direct ?? 0, a.lookthrough ?? 0))
}

function exposureChartOption(rows: ExposureRow[]): EChartsOption {
  const visible = rows.slice(0, 12).reverse()
  return {
    animationDuration: 450,
    color: ['#24364b', '#e76f51'],
    grid: { top: 44, right: 24, bottom: 28, left: 116, containLabel: false },
    legend: {
      top: 0,
      left: 0,
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { color: '#56616f', fontFamily: 'system-ui', fontSize: 12 },
      data: ['Direct', 'Look-through'],
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value) => `${Number(value).toFixed(2)}%`,
    },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#7b838c', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#e8e5de' } },
      axisLine: { show: false },
    },
    yAxis: {
      type: 'category',
      data: visible.map((row) => row.name),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#303944', width: 106, overflow: 'truncate' },
    },
    series: [
      {
        name: 'Direct',
        type: 'bar',
        barMaxWidth: 11,
        itemStyle: { borderRadius: [0, 3, 3, 0] },
        data: visible.map((row) => row.direct),
      },
      {
        name: 'Look-through',
        type: 'bar',
        barMaxWidth: 11,
        itemStyle: { borderRadius: [0, 3, 3, 0] },
        data: visible.map((row) => row.lookthrough),
      },
    ],
  }
}

function navChartOption(points: NavPoint[]): EChartsOption {
  const ordered = [...points].sort((a, b) => a.nav_date.localeCompare(b.nav_date))
  const shareCodes = [...new Set(ordered.map((point) => point.share_code).filter((value): value is string => Boolean(value)))]
  const grouped = shareCodes.length > 0 ? shareCodes : ['单位净值']
  const series: NonNullable<EChartsOption['series']> = grouped.map((code) => ({
    name: code,
    type: 'line',
    showSymbol: false,
    smooth: false,
    sampling: 'lttb',
    emphasis: { focus: 'series' },
    data: ordered
      .filter((point) => shareCodes.length === 0 || point.share_code === code)
      .map((point) => [point.nav_date, toNumber(point.unit_nav)]),
  }))
  const marketPoints = ordered.filter((point) => toNumber(point.market_close) !== null)
  if (marketPoints.length > 0) {
    series.push({
      name: '场内收盘价',
      type: 'line',
      showSymbol: false,
      lineStyle: { type: 'dashed', width: 1.5 },
      data: marketPoints.map((point) => [point.nav_date, toNumber(point.market_close)]),
    })
  }

  return {
    animationDuration: 500,
    color: ['#24364b', '#e76f51', '#268a7b', '#c69136', '#846c9b', '#667085'],
    grid: { top: 42, right: 18, bottom: 38, left: 56 },
    tooltip: { trigger: 'axis' },
    legend: {
      type: 'scroll',
      top: 0,
      left: 0,
      textStyle: { color: '#56616f', fontFamily: 'system-ui', fontSize: 12 },
    },
    xAxis: {
      type: 'time',
      axisLabel: { color: '#7b838c', hideOverlap: true },
      axisLine: { lineStyle: { color: '#d9d6cf' } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#7b838c' },
      splitLine: { lineStyle: { color: '#ece9e2' } },
    },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 4 }],
    series,
  }
}

function dailyReturn(point: NavPoint): number | null {
  return toNumber(point.published_daily_return_pct) ?? toNumber(point.calculated_daily_return_pct)
}

function formatSignedPercent(value: unknown): string {
  const number = toNumber(value)
  if (number === null) return '—'
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`
}

function returnTone(value: unknown): string {
  const number = toNumber(value)
  if (number === null || number === 0) return ''
  return number > 0 ? 'return-positive' : 'return-negative'
}

function dailyReturnChartOption(points: NavPoint[]): EChartsOption {
  const ordered = [...points].sort((a, b) => a.nav_date.localeCompare(b.nav_date))
  const shareCodes = [...new Set(ordered.map((point) => point.share_code).filter((value): value is string => Boolean(value)))]
  const grouped = shareCodes.length > 0 ? shareCodes : ['每日涨跌幅']
  return {
    animationDuration: 450,
    color: ['#e76f51', '#24364b', '#268a7b', '#c69136', '#846c9b'],
    grid: { top: 42, right: 18, bottom: 38, left: 56 },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value) => `${Number(value).toFixed(2)}%`,
    },
    legend: {
      type: 'scroll',
      top: 0,
      left: 0,
      textStyle: { color: '#56616f', fontFamily: 'system-ui', fontSize: 12 },
    },
    xAxis: {
      type: 'time',
      axisLabel: { color: '#7b838c', hideOverlap: true },
      axisLine: { lineStyle: { color: '#d9d6cf' } },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#7b838c', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#ece9e2' } },
    },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 4 }],
    series: grouped.map((code) => ({
      name: shareCodes.length > 0 ? `${code} 日涨跌幅` : code,
      type: 'line',
      showSymbol: false,
      smooth: false,
      data: ordered
        .filter((point) => shareCodes.length === 0 || point.share_code === code)
        .map((point) => [point.nav_date, dailyReturn(point)]),
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { color: '#b9b3a8', width: 1 },
        data: [{ yAxis: 0 }],
      },
    })),
  }
}

function relationTarget(relation: FundRelation): string {
  return displayText(
    relation.target_fund_name
      ?? relation.external_target_name
      ?? relation.external_target_code
      ?? relation.target_fund_contract_id,
    '目标未识别',
  )
}

function reportSourceUrl(report: Record<string, unknown>): string | null {
  const value = report.source_page_url ?? report.document_url
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) ? value : null
  } catch {
    return null
  }
}

const availabilityLabels: Record<PurchaseLimitAvailabilityState, string> = {
  OPEN: '开放',
  PAUSED: '暂停',
  UNKNOWN: '可售状态未知',
  NOT_SOLD: '该渠道未销售',
  NOT_APPLICABLE: '不适用',
}

const capLabels: Record<PurchaseLimitCapState, string> = {
  LIMITED: '有限额',
  UNLIMITED: '不限额',
  UNKNOWN: '限额未知',
}

function availabilityTone(value: PurchaseLimitAvailabilityState): string {
  if (value === 'OPEN') return 'success'
  if (value === 'PAUSED') return 'failed'
  if (value === 'UNKNOWN') return 'warning'
  return 'neutral'
}

function capTone(value: PurchaseLimitCapState): string {
  if (value === 'UNLIMITED') return 'success'
  if (value === 'LIMITED') return 'warning'
  return 'neutral'
}

function channelLabel(limit: PurchaseLimit): string {
  if (limit.channel_type === 'DIRECT') return displayText(limit.channel_name, '基金直销')
  if (limit.channel_key.trim().toUpperCase() === 'ALL_DISTRIBUTORS') return '全部代销'
  const name = limit.channel_name.trim()
  if (name) return `代销 · ${name}`
  if (limit.channel_key.trim().toUpperCase() === 'UNSPECIFIED') return '代销渠道未指明'
  return `代销 · ${limit.channel_key}`
}

function businessLabel(value: PurchaseLimit['business_type']): string {
  return {
    PURCHASE: '申购',
    RECURRING_INVESTMENT: '定期定额投资',
    CONVERSION_IN: '转换转入',
  }[value]
}

function limitBasisLabel(value: PurchaseLimit['limit_basis']): string {
  return value === 'PER_ACCOUNT_PER_DAY' ? '每账户每日' : '口径未知'
}

function shareScopeLabel(value: PurchaseLimit['share_scope']): string {
  return {
    PER_SHARE: '本份额独立',
    ALL_SHARES_COMBINED: '同合同各份额合并',
    UNKNOWN: '份额范围未知',
  }[value]
}

function purchaseCapValue(limit: PurchaseLimit): string {
  if (limit.cap_state === 'UNLIMITED') return '不限额'
  if (limit.cap_state === 'UNKNOWN') return '限额未知'
  const amount = toNumber(limit.daily_limit_amount)
  if (amount === null) return '有限额，金额缺失'
  try {
    return `${new Intl.NumberFormat('zh-CN', {
      style: 'currency',
      currency: limit.currency,
      maximumFractionDigits: 2,
    }).format(amount)} / 日`
  } catch {
    return `${formatMoney(amount)} ${limit.currency} / 日`
  }
}

function safeSourceUrl(value: string): string | null {
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) ? value : null
  } catch {
    return null
  }
}

export function FundDetailPage() {
  const { fundId = '' } = useParams()
  const enabled = Boolean(fundId)
  const fundQuery = useQuery({
    queryKey: ['fund', fundId],
    queryFn: ({ signal }) => api.fund(fundId, signal),
    enabled,
  })
  const sharesQuery = useQuery({
    queryKey: ['fund', fundId, 'shares'],
    queryFn: ({ signal }) => api.shares(fundId, signal),
    enabled,
  })
  const reportsQuery = useQuery({
    queryKey: ['fund', fundId, 'reports'],
    queryFn: ({ signal }) => api.reports(fundId, signal),
    enabled,
  })
  const countryDirectQuery = useQuery({
    queryKey: ['fund', fundId, 'country-exposure', 'direct'],
    queryFn: ({ signal }) => api.countryExposure(fundId, 'direct', signal),
    enabled,
  })
  const countryLookthroughQuery = useQuery({
    queryKey: ['fund', fundId, 'country-exposure', 'lookthrough'],
    queryFn: ({ signal }) => api.countryExposure(fundId, 'lookthrough', signal),
    enabled,
  })
  const industryDirectQuery = useQuery({
    queryKey: ['fund', fundId, 'industry-exposure', 'direct'],
    queryFn: ({ signal }) => api.industryExposure(fundId, 'direct', signal),
    enabled,
  })
  const industryLookthroughQuery = useQuery({
    queryKey: ['fund', fundId, 'industry-exposure', 'lookthrough'],
    queryFn: ({ signal }) => api.industryExposure(fundId, 'lookthrough', signal),
    enabled,
  })
  const holdingsQuery = useQuery({
    queryKey: ['fund', fundId, 'holdings'],
    queryFn: ({ signal }) => api.holdings(fundId, signal),
    enabled,
  })
  const fundHoldingsQuery = useQuery({
    queryKey: ['fund', fundId, 'fund-holdings'],
    queryFn: ({ signal }) => api.fundHoldings(fundId, signal),
    enabled,
  })
  const navQuery = useQuery({
    queryKey: ['fund', fundId, 'nav'],
    queryFn: ({ signal }) => api.nav(fundId, signal),
    enabled,
  })
  const purchaseLimitsQuery = useQuery({
    queryKey: ['fund', fundId, 'purchase-limits'],
    queryFn: ({ signal }) => api.purchaseLimits(fundId, {}, signal),
    enabled,
  })
  const relationsQuery = useQuery({
    queryKey: ['fund', fundId, 'relations'],
    queryFn: ({ signal }) => api.relations(fundId, signal),
    enabled,
  })
  const issuesQuery = useQuery({
    queryKey: ['data-quality-issues'],
    queryFn: ({ signal }) => api.dataQualityIssues(signal),
    enabled,
  })

  const countryItems = useMemo(
    () => [...(countryDirectQuery.data ?? []), ...(countryLookthroughQuery.data ?? [])],
    [countryDirectQuery.data, countryLookthroughQuery.data],
  )
  const industryItems = useMemo(
    () => [...(industryDirectQuery.data ?? []), ...(industryLookthroughQuery.data ?? [])],
    [industryDirectQuery.data, industryLookthroughQuery.data],
  )
  const countryRows = useMemo(() => exposureRows(countryItems), [countryItems])
  const industryRows = useMemo(() => exposureRows(industryItems), [industryItems])
  const countryOption = useMemo(() => exposureChartOption(countryRows), [countryRows])
  const industryOption = useMemo(() => exposureChartOption(industryRows), [industryRows])
  const navOption = useMemo(() => navChartOption(navQuery.data ?? []), [navQuery.data])
  const returnOption = useMemo(() => dailyReturnChartOption(navQuery.data ?? []), [navQuery.data])
  const hasReturnData = useMemo(
    () => (navQuery.data ?? []).some((point) => dailyReturn(point) !== null),
    [navQuery.data],
  )

  if (fundQuery.isPending) return <LoadingPanel label="正在组装基金证据链…" />
  if (fundQuery.isError) return <ErrorPanel error={fundQuery.error} onRetry={() => fundQuery.refetch()} />

  const fund = fundQuery.data
  const reports = reportsQuery.data ?? []
  const latestReport = reports
    .filter((report) => report.report_type === 'QUARTERLY' || report.report_quarter)
    .sort((a, b) => String(b.period_end ?? '').localeCompare(String(a.period_end ?? '')))[0]
  const issues = (issuesQuery.data ?? []).filter((issue) =>
    String(issue.fund_contract_id ?? '') === String(fund.id)
    || issue.representative_code === fund.representative_code,
  )

  return (
    <div className="page-stack detail-page">
      <Link className="back-link" to="/"><ArrowLeft size={16} />返回基金总览</Link>

      <section className="detail-hero">
        <div className="detail-title">
          <div className="code-chip">{fund.representative_code}</div>
          <div>
            <span className="eyebrow"><Landmark size={14} />{fund.manager_name}</span>
            <h1>{fund.canonical_name}</h1>
            <div className="detail-tags">
              <span>{displayText(fund.original_category, '原分类未提供')}</span>
              <span>{techScopeLabel(field(fund, 'tech_scope'))}</span>
              <span>{wrapperLabel(field(fund, 'wrapper_type'))}</span>
              {latestReport && <StatusBadge value={latestReport.parse_status} />}
            </div>
          </div>
        </div>
        <div className="as-of-card">
          <CalendarDays size={18} />
          <span>数据基准日</span>
          <strong>{formatDate(field(fund, 'data_as_of') ?? latestReport?.period_end)}</strong>
          <small>穿透口径可能因底层基金报告不同步而滞后</small>
        </div>
      </section>

      <section className="metric-grid" aria-label="基金披露指标">
        <MetricCard label="股票仓位" value={formatPercent(field(fund, 'equity_nav_pct'))} detail="占基金净值" icon={PieChart} />
        <MetricCard label="基金投资" value={formatPercent(field(fund, 'fund_investment_nav_pct'))} detail="ETF / FOF 等" icon={Boxes} tone="coral" />
        <MetricCard label="美国暴露" value={formatPercent(field(fund, 'us_country_pct'))} detail="报告 direct 口径" icon={Globe2} tone="gold" />
        <MetricCard label="信息技术" value={formatPercent(field(fund, 'information_technology_pct'))} detail="报告行业口径" icon={BarChart3} tone="jade" />
        <MetricCard label="前十大披露" value={formatPercent(field(fund, 'disclosed_top10_pct'))} detail="占基金净值" icon={ShieldCheck} />
        <MetricCard label="穿透覆盖" value={formatPercent(field(fund, 'lookthrough_coverage_pct'))} detail={`未解析基金 ${formatPercent(field(fund, 'unresolved_fund_weight_pct'))}`} icon={Network} tone="coral" />
      </section>

      <div className="detail-grid detail-grid-sidebar">
        <section className="panel" aria-labelledby="shares-title">
          <div className="panel-heading">
            <div><span className="section-kicker">CONTRACT</span><h2 id="shares-title">份额与基本信息</h2></div>
          </div>
          <dl className="fact-list">
            <div><dt>策略类型</dt><dd>{displayText(fund.strategy_type)}</dd></div>
            <div><dt>经济暴露族</dt><dd>{fund.exposure_families?.map((item) => item.display_name).join('、') || '未提供'}</dd></div>
            <div><dt>最大穿透深度</dt><dd>{displayText(field(fund, 'max_lookthrough_depth'))}</dd></div>
          </dl>
          {sharesQuery.isPending && <LoadingPanel label="载入份额…" />}
          {sharesQuery.isError && <ErrorPanel compact error={sharesQuery.error} onRetry={() => sharesQuery.refetch()} />}
          {sharesQuery.isSuccess && sharesQuery.data.length === 0 && <EmptyPanel compact title="暂无份额" detail="尚未导入 fund_share。" />}
          {sharesQuery.isSuccess && sharesQuery.data.length > 0 && (
            <div className="share-list">
              {sharesQuery.data.map((share) => (
                <div className="share-chip" key={String(share.id ?? share.share_code)}>
                  <strong>{share.share_code}</strong>
                  <span>{displayText(share.share_class, '未分级')} · {displayText(share.currency, '币种未标注')}</span>
                  {share.is_exchange_traded && <small>{displayText(share.exchange, '场内')}</small>}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel relation-panel" aria-labelledby="relation-title">
          <div className="panel-heading">
            <div><span className="section-kicker">LOOK-THROUGH</span><h2 id="relation-title">ETF / FOF 穿透链</h2></div>
            <GitBranch size={20} />
          </div>
          {relationsQuery.isPending && <LoadingPanel label="解析基金关系…" />}
          {relationsQuery.isError && <ErrorPanel compact error={relationsQuery.error} onRetry={() => relationsQuery.refetch()} />}
          {relationsQuery.isSuccess && relationsQuery.data.length === 0 && (
            <EmptyPanel compact title="没有披露基金关系" detail="这可能是一只直接持股基金，或关系尚未解析。" />
          )}
          {relationsQuery.isSuccess && relationsQuery.data.length > 0 && (
            <div className="relation-flow">
              <div className="relation-source"><span>当前基金</span><strong>{fund.representative_code}</strong></div>
              <div className="relation-branches">
                {relationsQuery.data.map((relation, index) => (
                  <div className="relation-item" key={String(relation.id ?? `${relation.relation_type}-${index}`)}>
                    <div className="relation-line"><i /><span>{relationTypeLabel(relation.relation_type)}</span></div>
                    <div className="relation-target">
                      <strong>{relationTarget(relation)}</strong>
                      <span>权重 {formatPercent(relation.weight_nav_pct)} · 置信度 {formatConfidence(relation.confidence)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </div>

      <PurchaseLimitPanel
        limits={purchaseLimitsQuery.data ?? []}
        pending={purchaseLimitsQuery.isPending}
        error={purchaseLimitsQuery.error}
        onRetry={() => purchaseLimitsQuery.refetch()}
      />

      <div className="detail-grid">
        <section className="panel chart-panel" aria-labelledby="country-title">
          <div className="panel-heading">
            <div><span className="section-kicker">GEOGRAPHY</span><h2 id="country-title">国家 / 地区暴露</h2></div>
            <span className="panel-caption">Direct vs Look-through</span>
          </div>
          {countryDirectQuery.isPending && countryLookthroughQuery.isPending && <LoadingPanel label="载入国家暴露…" />}
          {countryDirectQuery.isError && <ErrorPanel compact error={countryDirectQuery.error} onRetry={() => countryDirectQuery.refetch()} />}
          {countryLookthroughQuery.isError && <ErrorPanel compact error={countryLookthroughQuery.error} onRetry={() => countryLookthroughQuery.refetch()} />}
          {!countryDirectQuery.isPending && !countryLookthroughQuery.isPending && countryRows.length === 0 && (
            <EmptyPanel compact title="国家暴露不可用" detail="空结果不等于没有海外风险；请结合基金关系查看。" icon="warning" />
          )}
          {countryRows.length > 0 && (
            <EChart option={countryOption} ariaLabel="基金直接与穿透国家暴露对比图" />
          )}
        </section>

        <section className="panel chart-panel" aria-labelledby="industry-title">
          <div className="panel-heading">
            <div><span className="section-kicker">SECTORS</span><h2 id="industry-title">行业暴露</h2></div>
            <span className="panel-caption">报告标准行业</span>
          </div>
          {industryDirectQuery.isPending && industryLookthroughQuery.isPending && <LoadingPanel label="载入行业暴露…" />}
          {industryDirectQuery.isError && <ErrorPanel compact error={industryDirectQuery.error} onRetry={() => industryDirectQuery.refetch()} />}
          {industryLookthroughQuery.isError && <ErrorPanel compact error={industryLookthroughQuery.error} onRetry={() => industryLookthroughQuery.refetch()} />}
          {!industryDirectQuery.isPending && !industryLookthroughQuery.isPending && industryRows.length === 0 && (
            <EmptyPanel compact title="行业暴露不可用" detail="来源未披露或底层基金尚未可靠穿透。" />
          )}
          {industryRows.length > 0 && (
            <EChart option={industryOption} ariaLabel="基金直接与穿透行业暴露对比图" />
          )}
        </section>
      </div>

      <section className="panel chart-panel" aria-labelledby="nav-title">
        <div className="panel-heading">
          <div><span className="section-kicker">NAV ARCHIVE</span><h2 id="nav-title">每日净值与场内价格</h2></div>
          <div className="chart-legend-note"><LineChart size={16} />净值与场内价格保持不同序列</div>
        </div>
        {navQuery.isPending && <LoadingPanel label="载入历史净值…" />}
        {navQuery.isError && <ErrorPanel compact error={navQuery.error} onRetry={() => navQuery.refetch()} />}
        {navQuery.isSuccess && navQuery.data.length === 0 && (
          <EmptyPanel compact title="净值尚未归档" detail="观察台不会使用场内价格替代官方净值。" />
        )}
        {navQuery.isSuccess && navQuery.data.length > 0 && (
          <div className="nav-chart-stack">
            <div>
              <div className="chart-subheading"><h3>单位净值</h3><span>原始净值序列</span></div>
              <EChart option={navOption} height={390} ariaLabel="基金每日单位净值和场内收盘价时间序列图" />
            </div>
            <div>
              <div className="chart-subheading">
                <h3>每日涨跌幅</h3>
                <span>最新 {formatDate(field(fund, 'latest_nav_date'))} · <strong className={returnTone(field(fund, 'latest_nav_return_pct'))}>{formatSignedPercent(field(fund, 'latest_nav_return_pct'))}</strong></span>
              </div>
              {hasReturnData ? (
                <EChart option={returnOption} height={310} ariaLabel="基金每日净值涨跌幅百分比时间序列图" />
              ) : (
                <EmptyPanel compact title="涨跌幅尚不可用" detail="净值存在，但来源未公布日涨跌幅且当前序列不足以计算。" />
              )}
            </div>
          </div>
        )}
      </section>

      <div className="detail-grid holdings-grid">
        <HoldingTable holdings={holdingsQuery.data ?? []} pending={holdingsQuery.isPending} error={holdingsQuery.error} onRetry={() => holdingsQuery.refetch()} />
        <FundHoldingTable holdings={fundHoldingsQuery.data ?? []} pending={fundHoldingsQuery.isPending} error={fundHoldingsQuery.error} onRetry={() => fundHoldingsQuery.refetch()} />
      </div>

      <div className="detail-grid detail-grid-sidebar">
        <section className="panel" aria-labelledby="reports-title">
          <div className="panel-heading">
            <div><span className="section-kicker">SOURCES</span><h2 id="reports-title">来源报告</h2></div>
            <FileText size={20} />
          </div>
          {reportsQuery.isPending && <LoadingPanel label="载入报告元数据…" />}
          {reportsQuery.isError && <ErrorPanel compact error={reportsQuery.error} onRetry={() => reportsQuery.refetch()} />}
          {reportsQuery.isSuccess && reports.length === 0 && <EmptyPanel compact title="报告尚未发现" detail="请在数据运维页查看失败原因。" />}
          {reportsQuery.isSuccess && reports.length > 0 && (
            <div className="report-list">
              {reports.map((report) => {
                const url = reportSourceUrl(report)
                return (
                  <article key={String(report.id)} className="report-row">
                    <div className="report-icon"><FileText size={18} /></div>
                    <div>
                      <strong>{report.report_year} Q{report.report_quarter} {reportTypeLabel(report.report_type)}</strong>
                      <span>{displayText(report.source_provider, '来源未标注')} · 截止 {formatDate(report.period_end)}</span>
                      {report.parse_error && <small>{report.parse_error}</small>}
                    </div>
                    <div className="report-meta">
                      <StatusBadge value={report.parse_status} />
                      <span>置信度 {formatConfidence(report.parse_confidence)}</span>
                    </div>
                    {url ? (
                      <a className="icon-link" href={url} target="_blank" rel="noreferrer" aria-label="打开来源报告">
                        <ExternalLink size={16} />
                      </a>
                    ) : <span className="link-unavailable">链接不可用</span>}
                  </article>
                )
              })}
            </div>
          )}
        </section>

        <section className="panel issue-panel" aria-labelledby="issues-title">
          <div className="panel-heading">
            <div><span className="section-kicker">QUALITY</span><h2 id="issues-title">数据问题</h2></div>
            <Gauge size={20} />
          </div>
          {issuesQuery.isPending && <LoadingPanel label="检查质量问题…" />}
          {issuesQuery.isError && <ErrorPanel compact error={issuesQuery.error} onRetry={() => issuesQuery.refetch()} />}
          {issuesQuery.isSuccess && issues.length === 0 && (
            <EmptyPanel compact title="没有关联的开放问题" detail="仅表示当前问题表未返回此基金的记录。" />
          )}
          {issuesQuery.isSuccess && issues.length > 0 && (
            <div className="issue-list">
              {issues.map((issue) => (
                <article key={String(issue.id)}>
                  <AlertTriangle size={17} />
                  <div><strong>{displayText(issue.issue_code ?? issue.issue_type, '数据质量问题')}</strong><p>{displayText(issue.message)}</p><small>{formatDate(issue.detected_at ?? issue.created_at, true)}</small></div>
                  <StatusBadge value={issue.severity} />
                </article>
              ))}
            </div>
          )}
          {latestReport && (
            <div className="confidence-card">
              <span>最新报告解析置信度</span>
              <strong>{formatConfidence(latestReport.parse_confidence)}</strong>
              <small>{statusLabel(latestReport.parse_status)}</small>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function PurchaseLimitPanel({ limits, pending, error, onRetry }: {
  limits: PurchaseLimit[]
  pending: boolean
  error: unknown
  onRetry: () => void
}) {
  const ordered = [...limits].sort((a, b) => (
    a.share_code.localeCompare(b.share_code)
    || a.channel_type.localeCompare(b.channel_type)
    || a.channel_key.localeCompare(b.channel_key)
    || a.business_type.localeCompare(b.business_type)
    || a.source_provider.localeCompare(b.source_provider)
  ))
  const snapshotDates = [...new Set(ordered.map((limit) => limit.snapshot_date))]

  return (
    <section className="panel purchase-limit-panel" aria-labelledby="purchase-limits-title">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">DAILY SALES LIMITS</span>
          <h2 id="purchase-limits-title">直销 / 代销每日申购限额</h2>
          <p>按份额、渠道与来源保留快照；不同来源不会被合并成一个推断值。</p>
        </div>
        <div className="limit-heading-meta">
          <WalletCards size={20} />
          <span>{snapshotDates.length === 1 ? `快照 ${formatDate(snapshotDates[0])}` : '各份额最新快照'}</span>
        </div>
      </div>
      {pending && <LoadingPanel label="载入每日渠道限额…" />}
      {Boolean(error) && <ErrorPanel compact error={error} onRetry={onRetry} />}
      {!pending && !error && ordered.length === 0 && (
        <EmptyPanel
          compact
          title="尚无限额快照"
          detail="没有记录不代表不限额；请在数据运维页检查每日抓取覆盖。"
          icon="warning"
        />
      )}
      {!pending && !error && ordered.length > 0 && (
        <div className="purchase-limit-grid">
          {ordered.map((limit) => {
            const sourceUrl = safeSourceUrl(limit.source_url)
            return (
              <article className="purchase-limit-card" key={String(limit.id)}>
                <div className="limit-card-head">
                  <div><code>{limit.share_code}</code><strong>{channelLabel(limit)}</strong></div>
                  <span>{businessLabel(limit.business_type)}</span>
                </div>
                <div className="limit-status-row">
                  <StatusBadge value={availabilityTone(limit.availability_state)} label={availabilityLabels[limit.availability_state]} />
                  <StatusBadge value={capTone(limit.cap_state)} label={capLabels[limit.cap_state]} />
                </div>
                <strong className="limit-value">{purchaseCapValue(limit)}</strong>
                <dl className="limit-facts">
                  <div><dt>限额口径</dt><dd>{limitBasisLabel(limit.limit_basis)}</dd></div>
                  <div><dt>份额范围</dt><dd>{shareScopeLabel(limit.share_scope)}</dd></div>
                  <div><dt>生效日期</dt><dd>{formatDate(limit.effective_from)}</dd></div>
                  <div><dt>快照日期</dt><dd>{formatDate(limit.snapshot_date)}</dd></div>
                </dl>
                <div className="limit-source">
                  <span>{displayText(limit.source_provider, '来源未标注')}</span>
                  {sourceUrl
                    ? <a href={sourceUrl} target="_blank" rel="noreferrer">查看来源<ExternalLink size={13} /></a>
                    : <small>来源链接不可用</small>}
                </div>
              </article>
            )
          })}
        </div>
      )}
      <p className="panel-note">“开放”与“暂停”描述渠道可售状态；“有限额 / 不限额 / 未知”描述金额上限，两者不可互相替代。具名代销仅代表该渠道。</p>
    </section>
  )
}

function HoldingTable({ holdings, pending, error, onRetry }: {
  holdings: SecurityHolding[]
  pending: boolean
  error: unknown
  onRetry: () => void
}) {
  return (
    <section className="panel" aria-labelledby="stock-holdings-title">
      <div className="panel-heading"><div><span className="section-kicker">DISCLOSED</span><h2 id="stock-holdings-title">前十大股票 / 存托凭证</h2></div></div>
      {pending && <LoadingPanel label="载入股票持仓…" />}
      {Boolean(error) && <ErrorPanel compact error={error} onRetry={onRetry} />}
      {!pending && !error && holdings.length === 0 && <EmptyPanel compact title="没有直接股票持仓" detail="可能是 ETF 联接基金；这不表示没有穿透股票风险。" icon="warning" />}
      {!pending && !error && holdings.length > 0 && (
        <div className="compact-table-wrap">
          <table className="data-table compact-table">
            <thead><tr><th>#</th><th>证券</th><th>市场</th><th className="numeric">公允价值</th><th className="numeric">净值占比</th></tr></thead>
            <tbody>{holdings.map((holding, index) => (
              <tr key={String(holding.id ?? `${holding.security_code_raw}-${index}`)}>
                <td>{holding.rank ?? index + 1}</td>
                <td><strong>{displayText(holding.security_name_zh ?? holding.security_name_en ?? holding.security_name_normalized ?? holding.security_name_raw, '证券名称缺失')}</strong><span className="table-subline">{displayText(holding.security_code_raw, '代码缺失')}</span></td>
                <td>{displayText(holding.market_normalized ?? holding.country_normalized)}</td>
                <td className="numeric">{formatMoney(holding.fair_value_cny)}</td>
                <td className="numeric metric-cell">{formatPercent(holding.nav_pct)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function FundHoldingTable({ holdings, pending, error, onRetry }: {
  holdings: FundHolding[]
  pending: boolean
  error: unknown
  onRetry: () => void
}) {
  return (
    <section className="panel" aria-labelledby="fund-holdings-title">
      <div className="panel-heading"><div><span className="section-kicker">UNDERLYING FUNDS</span><h2 id="fund-holdings-title">前十大基金投资</h2></div></div>
      {pending && <LoadingPanel label="载入基金持仓…" />}
      {Boolean(error) && <ErrorPanel compact error={error} onRetry={onRetry} />}
      {!pending && !error && holdings.length === 0 && <EmptyPanel compact title="没有披露基金投资" detail="直接持股基金通常没有此表；空值不用于推断。" />}
      {!pending && !error && holdings.length > 0 && (
        <div className="compact-table-wrap">
          <table className="data-table compact-table">
            <thead><tr><th>#</th><th>底层基金</th><th>识别</th><th className="numeric">公允价值</th><th className="numeric">净值占比</th></tr></thead>
            <tbody>{holdings.map((holding, index) => (
              <tr key={String(holding.id ?? `${holding.fund_code_raw}-${index}`)}>
                <td>{holding.rank ?? index + 1}</td>
                <td><strong>{displayText(holding.resolved_fund_name ?? holding.fund_name_normalized ?? holding.normalized_name ?? holding.fund_name_raw, '基金名称缺失')}</strong><span className="table-subline">{displayText(holding.fund_code_raw, '代码缺失')}</span></td>
                <td><StatusBadge value={holding.resolved || holding.is_unresolved === false ? 'resolved' : 'unresolved'} /></td>
                <td className="numeric">{formatMoney(holding.fair_value_cny)}</td>
                <td className="numeric metric-cell">{formatPercent(holding.nav_pct)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </section>
  )
}
