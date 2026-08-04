import { useQueries } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import {
  ArrowDown,
  ArrowUp,
  CalendarRange,
  ChevronDown,
  CircleGauge,
  Download,
  RefreshCw,
  TrendingUp,
} from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type {
  ActiveTechPeriod,
  ActiveTechPool,
  ActiveTechReturnFund,
  ActiveTechReturnsPayload,
} from '../api/types'
import { EChart } from '../components/EChart'
import { MetricCard } from '../components/MetricCard'
import { ErrorPanel, LoadingPanel } from '../components/StatePanel'
import { exportDashboardPng } from '../lib/exportDashboardPng'
import { formatDate, toNumber } from '../lib/format'

const periods: ActiveTechPeriod[] = ['DAILY', 'MTD', 'QTD']

type ReturnPayloads = Record<ActiveTechPeriod, ActiveTechReturnsPayload>
type CombinedReturnRow = {
  fund: ActiveTechReturnFund
  returns: Record<ActiveTechPeriod, ActiveTechReturnFund>
}
type ReturnSortKey = 'FUND' | 'POOL' | ActiveTechPeriod | 'LATEST_NAV_DATE' | 'LAG'
type SortDirection = 'asc' | 'desc'
type ReturnSort = { key: ReturnSortKey; direction: SortDirection }

const periodLabels: Record<ActiveTechPeriod, string> = {
  DAILY: '每日',
  MTD: '本月 MTD',
  QTD: '本季度 QTD',
}

const statusLabels: Record<ActiveTechReturnFund['status'], string> = {
  READY: '可比较',
  STALE: '净值滞后',
  MISSING_NAV: '缺少净值',
  MISSING_BASELINE: '缺少区间基准',
}

function signedPercent(value: unknown): string {
  const number = toNumber(value)
  return number === null ? '—' : `${number > 0 ? '+' : ''}${number.toFixed(2)}%`
}

function returnSummaryOption(payloads: ReturnPayloads): EChartsOption {
  const values = periods.map((period) => ({
    period,
    average: toNumber(payloads[period].average_return_pct),
    median: toNumber(payloads[period].median_return_pct),
  }))
  const barData = (key: 'average' | 'median') => values.map((item) => {
    const value = item[key]
    return {
      value,
      label: value !== null && value < 0
        ? { position: 'insideLeft' as const, color: key === 'average' ? '#ffffff' : '#7b5c1d' }
        : { position: 'right' as const },
    }
  })
  return {
    grid: { top: 46, right: 78, bottom: 28, left: 112 },
    legend: {
      top: 0,
      left: 0,
      data: ['平均值', '中位数'],
      textStyle: { color: '#56616f', fontSize: 11 },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value) => signedPercent(value),
    },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#7b838c', formatter: (value: number) => `${value}%` },
      axisLine: { show: true, lineStyle: { color: '#303944' } },
      splitLine: { lineStyle: { color: '#ece9e2' } },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: periods.map((period) => periodLabels[period]),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#303944', fontWeight: 700 },
    },
    series: [
      {
        name: '平均值',
        type: 'bar',
        barMaxWidth: 18,
        data: barData('average'),
        itemStyle: { color: '#24364b' },
        label: { show: true, color: '#303944', formatter: ({ value }: { value: unknown }) => signedPercent(value) },
      },
      {
        name: '中位数',
        type: 'bar',
        barMaxWidth: 18,
        data: barData('median'),
        itemStyle: { color: '#ffffff', borderColor: '#c69136', borderWidth: 2 },
        label: { show: true, color: '#7b5c1d', formatter: ({ value }: { value: unknown }) => signedPercent(value) },
      },
    ],
  }
}

function combineReturnRows(payloads: ReturnPayloads): CombinedReturnRow[] {
  const byPeriod = Object.fromEntries(periods.map((period) => [
    period,
    new Map(payloads[period].items.map((item) => [item.representative_code, item])),
  ])) as Record<ActiveTechPeriod, Map<string, ActiveTechReturnFund>>
  const codes = [...new Set(periods.flatMap((period) => payloads[period].items.map((item) => item.representative_code)))]
  return codes.flatMap((code) => {
    const daily = byPeriod.DAILY.get(code)
    const mtd = byPeriod.MTD.get(code)
    const qtd = byPeriod.QTD.get(code)
    return daily && mtd && qtd ? [{ fund: daily, returns: { DAILY: daily, MTD: mtd, QTD: qtd } }] : []
  })
}

function sortValue(row: CombinedReturnRow, key: ReturnSortKey): number | string | null {
  if (key === 'FUND') return row.fund.representative_code
  if (key === 'POOL') return row.fund.pool_segment
  if (key === 'LATEST_NAV_DATE') return row.fund.latest_official_nav_date
  if (key === 'LAG') return row.fund.nav_lag_days
  return toNumber(row.returns[key].return_pct)
}

function sortRows(rows: CombinedReturnRow[], sort: ReturnSort): CombinedReturnRow[] {
  return [...rows].sort((left, right) => {
    const leftValue = sortValue(left, sort.key)
    const rightValue = sortValue(right, sort.key)
    if (leftValue === null && rightValue === null) return left.fund.representative_code.localeCompare(right.fund.representative_code)
    if (leftValue === null) return 1
    if (rightValue === null) return -1
    const difference = typeof leftValue === 'number' && typeof rightValue === 'number'
      ? leftValue - rightValue
      : String(leftValue).localeCompare(String(rightValue), 'zh-CN')
    if (difference === 0) return left.fund.representative_code.localeCompare(right.fund.representative_code)
    return sort.direction === 'asc' ? difference : -difference
  })
}

function SortableHeader({
  columnKey,
  label,
  sort,
  numeric = false,
  onSort,
}: {
  columnKey: ReturnSortKey
  label: string
  sort: ReturnSort
  numeric?: boolean
  onSort: (key: ReturnSortKey) => void
}) {
  const active = sort.key === columnKey
  return (
    <th className={numeric ? 'numeric' : undefined} aria-sort={active ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button className={active ? 'sort-button is-active' : 'sort-button'} type="button" onClick={() => onSort(columnKey)}>
        {label}
        {active && (sort.direction === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
      </button>
    </th>
  )
}

function ReturnCell({ item }: { item: ActiveTechReturnFund }) {
  const value = toNumber(item.return_pct)
  const dates = item.baseline_date && item.end_date
    ? `${formatDate(item.baseline_date)} → ${formatDate(item.end_date)}`
    : statusLabels[item.status]
  const detail = [
    item.status !== 'READY' ? statusLabels[item.status] : null,
    item.uses_accumulated_nav ? '累计净值' : null,
    dates,
  ].filter((part, index, all) => part && all.indexOf(part) === index).join(' · ')
  return (
    <td className={value === null ? 'numeric' : value >= 0 ? 'numeric return-positive' : 'numeric return-negative'}>
      <strong>{signedPercent(item.return_pct)}</strong>
      <small className="calculation-note">{detail}</small>
    </td>
  )
}

export function ActiveTechReturnsPage() {
  const [pool, setPool] = useState<ActiveTechPool>('CORE')
  const [sort, setSort] = useState<ReturnSort>({ key: 'QTD', direction: 'desc' })
  const [exportState, setExportState] = useState<'IDLE' | 'EXPORTING' | 'ERROR'>('IDLE')
  const [exportError, setExportError] = useState<string | null>(null)
  const dashboardRef = useRef<HTMLDivElement>(null)
  const [dailyQuery, mtdQuery, qtdQuery] = useQueries({
    queries: periods.map((period) => ({
      queryKey: ['active-tech-returns', pool, period],
      queryFn: ({ signal }: { signal: AbortSignal }) => api.activeTechReturns({ pool, period }, signal),
    })),
  })
  const queries = [dailyQuery, mtdQuery, qtdQuery]
  const payloads = useMemo<ReturnPayloads | null>(
    () => dailyQuery.data && mtdQuery.data && qtdQuery.data
      ? { DAILY: dailyQuery.data, MTD: mtdQuery.data, QTD: qtdQuery.data }
      : null,
    [dailyQuery.data, mtdQuery.data, qtdQuery.data],
  )
  const rows = useMemo(() => payloads ? combineReturnRows(payloads) : [], [payloads])
  const sorted = useMemo(() => sortRows(rows, sort), [rows, sort])
  const chartOption = useMemo(() => payloads ? returnSummaryOption(payloads) : {}, [payloads])
  const queryError = queries.find((query) => query.isError)?.error
  const isFetching = queries.some((query) => query.isFetching)
  const dataQualityCount = payloads
    ? Math.max(...periods.map((period) => payloads[period].missing_fund_count + payloads[period].stale_fund_count))
    : 0

  function toggleSort(key: ReturnSortKey) {
    setSort((current) => ({
      key,
      direction: current.key === key
        ? (current.direction === 'desc' ? 'asc' : 'desc')
        : (key === 'FUND' || key === 'POOL' ? 'asc' : 'desc'),
    }))
  }

  function refreshAll() {
    void Promise.all(queries.map((query) => query.refetch()))
  }

  async function exportPng() {
    if (!dashboardRef.current || !payloads) return
    setExportState('EXPORTING')
    setExportError(null)
    try {
      await exportDashboardPng(dashboardRef.current, {
        filename: `active-tech-returns-${pool.toLowerCase()}-all-periods-${payloads.DAILY.common_comparable_date ?? payloads.DAILY.as_of}.png`,
        width: 1440,
        height: 2200,
      })
      setExportState('IDLE')
    } catch (error) {
      console.error('Dashboard PNG export failed', error)
      setExportError(error instanceof Error ? error.message : '未知浏览器错误')
      setExportState('ERROR')
    }
  }

  return (
    <div ref={dashboardRef} className="page-stack dashboard-page active-tech-returns-page">
      <section className="page-intro dashboard-intro">
        <div>
          <span className="eyebrow"><TrendingUp size={14} />ACTIVE TECH RETURNS</span>
          <h1>主动科技 QDII 收益看板</h1>
          <p>每日、本月和本季度收益统一比较；按共同可比截止日读取正式净值，累计净值可用时优先采用。</p>
        </div>
        <div className="dashboard-actions">
          <button className="button button-primary dashboard-export-button" type="button" onClick={exportPng} disabled={!payloads || exportState === 'EXPORTING'}>
            <Download size={16} />{exportState === 'EXPORTING' ? '生成中…' : '导出整页 PNG'}
          </button>
          {exportState === 'ERROR' && <small role="alert">PNG 生成失败：{exportError}</small>}
        </div>
      </section>

      <section className="dashboard-filter-bar" aria-label="收益看板筛选">
        <label><span>基金池</span><span className="select-field"><select value={pool} onChange={(event) => setPool(event.target.value as ActiveTechPool)}><option value="CORE">核心 18 只</option><option value="BROAD">广义 33 只</option></select><ChevronDown size={15} /></span></label>
        <button className="button button-secondary dashboard-refresh" type="button" onClick={refreshAll} disabled={isFetching}><RefreshCw size={15} />刷新</button>
      </section>

      {queries.some((query) => query.isPending) && <LoadingPanel label="正在计算每日、本月和本季度收益…" />}
      {queryError && <ErrorPanel error={queryError} onRetry={refreshAll} />}
      {payloads && (
        <>
          <section className="dashboard-date-strip" aria-label="数据日期">
            <div><span>页面请求日</span><strong>{formatDate(payloads.DAILY.as_of)}</strong></div>
            <div><span>最近同步日期</span><strong>{formatDate(payloads.DAILY.sync_date)}</strong></div>
            <div><span>最新正式净值日</span><strong>{formatDate(payloads.DAILY.latest_official_nav_date)}</strong></div>
            <div><span>共同可比日期</span><strong>{formatDate(payloads.DAILY.common_comparable_date)}</strong></div>
          </section>

          <section className="metric-grid dashboard-metric-grid">
            <MetricCard label="每日平均收益" value={signedPercent(payloads.DAILY.average_return_pct)} detail={`${payloads.DAILY.comparable_fund_count} 只可比较`} icon={TrendingUp} tone="coral" />
            <MetricCard label="本月平均收益" value={signedPercent(payloads.MTD.average_return_pct)} detail={`${payloads.MTD.comparable_fund_count} 只可比较`} icon={CalendarRange} tone="jade" />
            <MetricCard label="本季度平均收益" value={signedPercent(payloads.QTD.average_return_pct)} detail={`${payloads.QTD.comparable_fund_count} 只可比较`} icon={CircleGauge} tone="ink" />
            <MetricCard label="数据质量" value={`${dataQualityCount}`} detail={`日 ${payloads.DAILY.missing_fund_count + payloads.DAILY.stale_fund_count} · 月 ${payloads.MTD.missing_fund_count + payloads.MTD.stale_fund_count} · 季 ${payloads.QTD.missing_fund_count + payloads.QTD.stale_fund_count}`} icon={CircleGauge} tone="gold" />
          </section>

          <section className="panel dashboard-chart-panel" aria-labelledby="return-summary-title">
            <div className="panel-heading">
              <div><span className="section-kicker">PERIOD COMPARISON</span><h2 id="return-summary-title">三期间收益概览</h2><p>同一基金池的平均值与中位数；0% 为盈亏分界，精确基金收益见下表。</p></div>
              <span className="panel-caption">日 {payloads.DAILY.comparable_fund_count} · 月 {payloads.MTD.comparable_fund_count} · 季 {payloads.QTD.comparable_fund_count}</span>
            </div>
            {periods.some((period) => payloads[period].comparable_fund_count > 0)
              ? <EChart option={chartOption} height={320} ariaLabel="每日、本月、本季度收益概览柱状图" />
              : <div className="dashboard-empty-chart">没有足够的正式净值计算收益概览。</div>}
          </section>

          <section className="panel dashboard-detail-panel" aria-labelledby="return-detail-title">
            <div className="panel-heading">
              <div><span className="section-kicker">FUND DETAIL</span><h2 id="return-detail-title">基金收益明细</h2><p>每日、本月和本季度集中展示；默认按本季度收益降序，点击表头可切换排序。</p></div>
              <span className="panel-caption">{payloads.DAILY.fund_count} / 配置 {payloads.DAILY.configured_fund_count} 只</span>
            </div>
            <div className="data-table-wrap dashboard-table-wrap">
              <table className="data-table dashboard-table">
                <thead><tr>
                  <SortableHeader columnKey="FUND" label="基金" sort={sort} onSort={toggleSort} />
                  <SortableHeader columnKey="POOL" label="池内角色" sort={sort} onSort={toggleSort} />
                  <SortableHeader columnKey="DAILY" label="每日" sort={sort} numeric onSort={toggleSort} />
                  <SortableHeader columnKey="MTD" label="本月 MTD" sort={sort} numeric onSort={toggleSort} />
                  <SortableHeader columnKey="QTD" label="本季度 QTD" sort={sort} numeric onSort={toggleSort} />
                  <SortableHeader columnKey="LATEST_NAV_DATE" label="最新正式净值日" sort={sort} onSort={toggleSort} />
                  <SortableHeader columnKey="LAG" label="滞后" sort={sort} numeric onSort={toggleSort} />
                </tr></thead>
                <tbody>
                  {sorted.map((row) => (
                    <tr key={row.fund.representative_code}>
                      <td><span className="dashboard-fund"><strong>{row.fund.fund_name}</strong><small>{row.fund.representative_code} · 份额 {row.fund.share_code ?? '—'}</small></span></td>
                      <td>{row.fund.pool_segment === 'CORE' ? '核心' : '动态'}</td>
                      <ReturnCell item={row.returns.DAILY} />
                      <ReturnCell item={row.returns.MTD} />
                      <ReturnCell item={row.returns.QTD} />
                      <td className="date-cell">{formatDate(row.fund.latest_official_nav_date)}</td>
                      <td className="numeric">{row.fund.nav_lag_days === null ? '—' : `${row.fund.nav_lag_days} 天`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="dashboard-risk-note">来源为本地归档的公开正式净值。收益不代表未来表现；各期间缺失基准的基金不进入对应均值、中位数和排序值。</p>
          </section>
        </>
      )}
    </div>
  )
}
