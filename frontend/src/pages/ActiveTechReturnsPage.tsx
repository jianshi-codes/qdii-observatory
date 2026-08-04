import { useQuery } from '@tanstack/react-query'
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
} from '../api/types'
import { EChart } from '../components/EChart'
import { MetricCard } from '../components/MetricCard'
import { ErrorPanel, LoadingPanel } from '../components/StatePanel'
import { StatusBadge } from '../components/StatusBadge'
import { exportDashboardPng } from '../lib/exportDashboardPng'
import { formatDate, toNumber } from '../lib/format'

type ReturnSortKey = 'FUND' | 'POOL' | 'RETURN' | 'BASELINE_DATE' | 'END_DATE' | 'LATEST_NAV_DATE' | 'LAG' | 'STATUS'
type SortDirection = 'asc' | 'desc'
type ReturnSort = { key: ReturnSortKey; direction: SortDirection }

const periodLabels: Record<ActiveTechPeriod, string> = {
  DAILY: '每日',
  MTD: '本月',
  QTD: '本季度',
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

function returnDistributionOption(items: ActiveTechReturnFund[]): EChartsOption {
  const values = items.map((item) => toNumber(item.return_pct)).filter((value): value is number => value !== null)
  if (!values.length) return { series: [] }
  const min = Math.min(...values)
  const max = Math.max(...values)
  const binCount = Math.min(9, Math.max(4, Math.ceil(Math.sqrt(values.length))))
  const span = max === min ? 1 : max - min
  const step = span / binCount
  const bins = Array.from({ length: binCount }, (_, index) => ({
    start: min + index * step,
    end: index === binCount - 1 ? max : min + (index + 1) * step,
    count: 0,
  }))
  for (const value of values) {
    const index = max === min ? 0 : Math.min(binCount - 1, Math.floor((value - min) / step))
    bins[index].count += 1
  }
  return {
    grid: { top: 18, right: 16, bottom: 42, left: 42 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params) => {
        const item = Array.isArray(params) ? params[0] : params
        return `${item?.name ?? ''}<br/>${item?.value ?? 0} 只基金`
      },
    },
    xAxis: {
      type: 'category',
      data: bins.map((bin) => `${bin.start.toFixed(1)}～${bin.end.toFixed(1)}%`),
      axisTick: { show: false },
      axisLabel: { color: '#7b838c', fontSize: 10, rotate: bins.length > 6 ? 18 : 0 },
      axisLine: { lineStyle: { color: '#cfcac0' } },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: '#7b838c' },
      splitLine: { lineStyle: { color: '#ece9e2' } },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 52,
      data: bins.map((bin) => ({
        value: bin.count,
        itemStyle: { color: bin.end < 0 ? '#268a7b' : '#e76f51' },
      })),
    }],
  }
}

function sortValue(item: ActiveTechReturnFund, key: ReturnSortKey): number | string | null {
  if (key === 'FUND') return item.representative_code
  if (key === 'POOL') return item.pool_segment
  if (key === 'RETURN') return toNumber(item.return_pct)
  if (key === 'BASELINE_DATE') return item.baseline_date
  if (key === 'END_DATE') return item.end_date
  if (key === 'LATEST_NAV_DATE') return item.latest_official_nav_date
  if (key === 'LAG') return item.nav_lag_days
  return statusLabels[item.status]
}

function sortItems(items: ActiveTechReturnFund[], sort: ReturnSort): ActiveTechReturnFund[] {
  return [...items].sort((left, right) => {
    const leftValue = sortValue(left, sort.key)
    const rightValue = sortValue(right, sort.key)
    if (leftValue === null && rightValue === null) return left.representative_code.localeCompare(right.representative_code)
    if (leftValue === null) return 1
    if (rightValue === null) return -1
    const difference = typeof leftValue === 'number' && typeof rightValue === 'number'
      ? leftValue - rightValue
      : String(leftValue).localeCompare(String(rightValue), 'zh-CN')
    if (difference === 0) return left.representative_code.localeCompare(right.representative_code)
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

export function ActiveTechReturnsPage() {
  const [pool, setPool] = useState<ActiveTechPool>('CORE')
  const [period, setPeriod] = useState<ActiveTechPeriod>('DAILY')
  const [sort, setSort] = useState<ReturnSort>({ key: 'RETURN', direction: 'desc' })
  const [exportState, setExportState] = useState<'IDLE' | 'EXPORTING' | 'ERROR'>('IDLE')
  const [exportError, setExportError] = useState<string | null>(null)
  const dashboardRef = useRef<HTMLDivElement>(null)
  const query = useQuery({
    queryKey: ['active-tech-returns', pool, period],
    queryFn: ({ signal }) => api.activeTechReturns({ pool, period }, signal),
  })
  const sorted = useMemo(() => sortItems(query.data?.items ?? [], sort), [query.data?.items, sort])
  const chartOption = useMemo(
    () => returnDistributionOption(query.data?.items ?? []),
    [query.data?.items],
  )

  function toggleSort(key: ReturnSortKey) {
    setSort((current) => ({
      key,
      direction: current.key === key
        ? (current.direction === 'desc' ? 'asc' : 'desc')
        : (key === 'FUND' || key === 'POOL' || key === 'STATUS' ? 'asc' : 'desc'),
    }))
  }

  async function exportPng() {
    if (!dashboardRef.current || !query.data) return
    setExportState('EXPORTING')
    setExportError(null)
    try {
      await exportDashboardPng(dashboardRef.current, {
        filename: `active-tech-returns-${pool.toLowerCase()}-${period.toLowerCase()}-${query.data.common_comparable_date ?? query.data.as_of}.png`,
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
          <p>按共同可比截止日计算正式净值收益；累计净值可用时优先采用，以纳入分红影响。</p>
        </div>
        <div className="dashboard-actions">
          <button
            className="button button-primary dashboard-export-button"
            type="button"
            onClick={exportPng}
            disabled={!query.data || exportState === 'EXPORTING'}
          >
            <Download size={16} />{exportState === 'EXPORTING' ? '生成中…' : '导出整页 PNG'}
          </button>
          {exportState === 'ERROR' && <small role="alert">PNG 生成失败：{exportError}</small>}
        </div>
      </section>

      <section className="dashboard-filter-bar" aria-label="收益看板筛选">
        <label><span>基金池</span><span className="select-field"><select value={pool} onChange={(event) => setPool(event.target.value as ActiveTechPool)}><option value="CORE">核心 18 只</option><option value="BROAD">广义 33 只</option></select><ChevronDown size={15} /></span></label>
        <label><span>期间</span><span className="select-field"><select value={period} onChange={(event) => setPeriod(event.target.value as ActiveTechPeriod)}><option value="DAILY">每日</option><option value="MTD">本月 MTD</option><option value="QTD">本季度 QTD</option></select><ChevronDown size={15} /></span></label>
        <button className="button button-secondary dashboard-refresh" type="button" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw size={15} />刷新</button>
      </section>

      {query.isPending && <LoadingPanel label="正在计算主动科技基金收益…" />}
      {query.isError && <ErrorPanel error={query.error} onRetry={() => query.refetch()} />}
      {query.data && (
        <>
          <section className="dashboard-date-strip" aria-label="数据日期">
            <div><span>页面请求日</span><strong>{formatDate(query.data.as_of)}</strong></div>
            <div><span>最近同步日期</span><strong>{formatDate(query.data.sync_date)}</strong></div>
            <div><span>最新正式净值日</span><strong>{formatDate(query.data.latest_official_nav_date)}</strong></div>
            <div><span>共同可比日期</span><strong>{formatDate(query.data.common_comparable_date)}</strong></div>
          </section>

          <section className="metric-grid dashboard-metric-grid">
            <MetricCard label={`${periodLabels[period]}平均收益`} value={signedPercent(query.data.average_return_pct)} detail={`${query.data.comparable_fund_count} 只可比较`} icon={TrendingUp} tone="coral" />
            <MetricCard label={`${periodLabels[period]}中位数`} value={signedPercent(query.data.median_return_pct)} detail="降低极端值影响" icon={CircleGauge} tone="ink" />
            <MetricCard label="上涨 / 下跌" value={`${query.data.positive_fund_count} / ${query.data.negative_fund_count}`} detail="零收益不计入两侧" icon={CalendarRange} tone="jade" />
            <MetricCard label="数据质量" value={`${query.data.missing_fund_count + query.data.stale_fund_count}`} detail={`${query.data.missing_fund_count} 缺失 · ${query.data.stale_fund_count} 滞后`} icon={CircleGauge} tone="gold" />
          </section>

          <section className="panel dashboard-chart-panel" aria-labelledby="return-distribution-title">
            <div className="panel-heading">
              <div><span className="section-kicker">DISTRIBUTION</span><h2 id="return-distribution-title">{periodLabels[period]}收益分布</h2><p>柱高为基金数量；中国市场惯例下红色表示正收益、绿色表示负收益。</p></div>
              <span className="panel-caption">样本 {query.data.comparable_fund_count} / {query.data.fund_count}</span>
            </div>
            {query.data.comparable_fund_count > 0
              ? <EChart option={chartOption} height={320} ariaLabel={`${periodLabels[period]}收益分布直方图`} />
              : <div className="dashboard-empty-chart">没有足够的正式净值计算收益分布。</div>}
          </section>

          <section className="panel dashboard-detail-panel" aria-labelledby="return-detail-title">
            <div className="panel-heading">
              <div><span className="section-kicker">FUND DETAIL</span><h2 id="return-detail-title">基金收益明细</h2><p>每个基金合同只采用一个代表份额，避免 A/C 类重复计数。</p></div>
              <span className="panel-caption">{query.data.fund_count} / 配置 {query.data.configured_fund_count} 只</span>
            </div>
            <div className="data-table-wrap dashboard-table-wrap">
              <table className="data-table dashboard-table">
                <thead><tr>
                  <SortableHeader columnKey="FUND" label="基金" sort={sort} onSort={toggleSort} />
                  <SortableHeader columnKey="POOL" label="池内角色" sort={sort} onSort={toggleSort} />
                  <SortableHeader columnKey="RETURN" label={`${periodLabels[period]}收益`} sort={sort} numeric onSort={toggleSort} />
                  <SortableHeader columnKey="BASELINE_DATE" label="基准净值日" sort={sort} onSort={toggleSort} />
                  <SortableHeader columnKey="END_DATE" label="截止净值日" sort={sort} onSort={toggleSort} />
                  <SortableHeader columnKey="LATEST_NAV_DATE" label="最新正式净值日" sort={sort} onSort={toggleSort} />
                  <SortableHeader columnKey="LAG" label="滞后" sort={sort} numeric onSort={toggleSort} />
                  <SortableHeader columnKey="STATUS" label="质量状态" sort={sort} onSort={toggleSort} />
                </tr></thead>
                <tbody>
                  {sorted.map((item) => (
                    <tr key={item.representative_code}>
                      <td><span className="dashboard-fund"><strong>{item.fund_name}</strong><small>{item.representative_code} · 份额 {item.share_code ?? '—'}</small></span></td>
                      <td>{item.pool_segment === 'CORE' ? '核心' : '动态'}</td>
                      <td className={toNumber(item.return_pct) !== null && Number(item.return_pct) >= 0 ? 'numeric return-positive' : 'numeric return-negative'}><strong>{signedPercent(item.return_pct)}</strong>{item.uses_accumulated_nav && <small className="calculation-note">累计净值</small>}</td>
                      <td className="date-cell">{formatDate(item.baseline_date)}</td>
                      <td className="date-cell">{formatDate(item.end_date)}</td>
                      <td className="date-cell">{formatDate(item.latest_official_nav_date)}</td>
                      <td className="numeric">{item.nav_lag_days === null ? '—' : `${item.nav_lag_days} 天`}</td>
                      <td><StatusBadge value={item.status} label={statusLabels[item.status]} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="dashboard-risk-note">来源为本地归档的公开正式净值。收益不代表未来表现；净值披露可能滞后，缺失基准的基金不进入均值与分布。</p>
          </section>
        </>
      )}
    </div>
  )
}
