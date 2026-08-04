import { useQuery } from '@tanstack/react-query'
import type { EChartsOption } from 'echarts'
import {
  CircleGauge,
  ChevronDown,
  Download,
  Globe2,
  Layers3,
  MapPinned,
  RefreshCw,
} from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import type {
  ActiveTechPool,
  ActiveTechRegionsPayload,
} from '../api/types'
import { EChart } from '../components/EChart'
import { MetricCard } from '../components/MetricCard'
import { EmptyPanel, ErrorPanel, LoadingPanel } from '../components/StatePanel'
import { StatusBadge } from '../components/StatusBadge'
import { exportDashboardPng } from '../lib/exportDashboardPng'
import { formatDate, formatPercent, toNumber } from '../lib/format'

const palette = ['#24364b', '#e76f51', '#268a7b', '#c69136', '#846c9b']

const missingReasonLabels = {
  MISSING_REPORT: '缺少季度报告',
  REPORT_NOT_PARSED: '季度报告未解析',
  MISSING_EXPOSURE: '缺少地区明细',
}

function stackedRegionOption(payload: ActiveTechRegionsPayload): EChartsOption {
  const countries = payload.average_distribution.slice(0, 4).map((item) => item.country)
  const seriesNames = [...countries, '其他已披露']
  const funds = [...payload.funds].sort((left, right) =>
    (toNumber(right.disclosed_country_pct) ?? 0) - (toNumber(left.disclosed_country_pct) ?? 0),
  )
  return {
    color: palette,
    grid: { top: 48, right: 28, bottom: 34, left: 98 },
    legend: { top: 0, left: 0, textStyle: { color: '#56616f', fontSize: 11 } },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value) => `${Number(value).toFixed(2)}%`,
    },
    xAxis: {
      type: 'value',
      max: 100,
      axisLabel: { color: '#7b838c', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#ece9e2' } },
    },
    yAxis: {
      type: 'category',
      data: funds.map((fund) => fund.representative_code),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#303944', fontFamily: 'monospace' },
    },
    series: seriesNames.map((country) => ({
      name: country,
      type: 'bar',
      stack: 'region',
      barMaxWidth: 16,
      data: funds.map((fund) => {
        if (country === '其他已披露') {
          return fund.allocations
            .filter((item) => !countries.includes(item.country))
            .reduce((total, item) => total + (toNumber(item.nav_pct) ?? 0), 0)
        }
        return toNumber(fund.allocations.find((item) => item.country === country)?.nav_pct) ?? 0
      }),
    })),
  }
}

function averageRegionOption(payload: ActiveTechRegionsPayload): EChartsOption {
  const items = payload.average_distribution.slice(0, 10).reverse()
  return {
    grid: { top: 16, right: 28, bottom: 28, left: 112 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (value) => `${Number(value).toFixed(2)}%` },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#7b838c', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#ece9e2' } },
    },
    yAxis: {
      type: 'category',
      data: items.map((item) => item.country),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#303944' },
    },
    series: [{
      type: 'bar',
      barMaxWidth: 18,
      data: items.map((item) => ({ value: toNumber(item.average_nav_pct), itemStyle: { color: '#24364b' } })),
      label: { show: true, position: 'right', color: '#56616f', formatter: ({ value }: { value: unknown }) => `${Number(value).toFixed(1)}%` },
    }],
  }
}

function averageCoverage(payload: ActiveTechRegionsPayload): number | null {
  if (!payload.covered_fund_count) return null
  const total = payload.funds.reduce(
    (sum, fund) => sum + (toNumber(fund.disclosed_country_pct) ?? 0),
    0,
  )
  return total / payload.covered_fund_count
}

function quarterKey(year: number, quarter: number): string {
  return `${year}-Q${quarter}`
}

export function ActiveTechRegionsPage() {
  const [pool, setPool] = useState<ActiveTechPool>('CORE')
  const [basis, setBasis] = useState<'DIRECT' | 'LOOKTHROUGH'>('DIRECT')
  const [selectedQuarter, setSelectedQuarter] = useState('')
  const [exportState, setExportState] = useState<'IDLE' | 'EXPORTING' | 'ERROR'>('IDLE')
  const [exportError, setExportError] = useState<string | null>(null)
  const dashboardRef = useRef<HTMLDivElement>(null)
  const selected = /^([0-9]{4})-Q([1-4])$/.exec(selectedQuarter)
  const query = useQuery({
    queryKey: ['active-tech-regions', pool, basis, selectedQuarter],
    queryFn: ({ signal }) => api.activeTechRegions({
      pool,
      basis,
      year: selected ? Number(selected[1]) : undefined,
      quarter: selected ? Number(selected[2]) : undefined,
    }, signal),
  })

  const displayedQuarter = selectedQuarter || (
    query.data?.report_year && query.data.report_quarter
      ? quarterKey(query.data.report_year, query.data.report_quarter)
      : ''
  )

  const stackedOption = useMemo(
    () => query.data ? stackedRegionOption(query.data) : {},
    [query.data],
  )
  const averageOption = useMemo(
    () => query.data ? averageRegionOption(query.data) : {},
    [query.data],
  )

  async function exportPng() {
    if (!dashboardRef.current || !query.data) return
    setExportState('EXPORTING')
    setExportError(null)
    try {
      await exportDashboardPng(dashboardRef.current, {
        filename: `active-tech-regions-${pool.toLowerCase()}-${basis.toLowerCase()}-${displayedQuarter || 'latest'}.png`,
        width: 1440,
        height: 2400,
      })
      setExportState('IDLE')
    } catch (error) {
      console.error('Dashboard PNG export failed', error)
      setExportError(error instanceof Error ? error.message : '未知浏览器错误')
      setExportState('ERROR')
    }
  }

  return (
    <div ref={dashboardRef} className="page-stack dashboard-page active-tech-regions-page">
      <section className="page-intro dashboard-intro">
        <div>
          <span className="eyebrow"><MapPinned size={14} />QUARTERLY REGIONS</span>
          <h1>主动科技 QDII 地区看板</h1>
          <p>按正式季度报告聚合地区暴露；直接披露与穿透结果分开呈现，不把缺失权重补成 100%。</p>
        </div>
        <div className="dashboard-actions">
          <button className="button button-primary dashboard-export-button" type="button" onClick={exportPng} disabled={!query.data || exportState === 'EXPORTING'}><Download size={16} />{exportState === 'EXPORTING' ? '生成中…' : '导出整页 PNG'}</button>
          {exportState === 'ERROR' && <small role="alert">PNG 生成失败：{exportError}</small>}
        </div>
      </section>

      <section className="dashboard-filter-bar" aria-label="地区看板筛选">
        <label><span>基金池</span><span className="select-field"><select value={pool} onChange={(event) => { setPool(event.target.value as ActiveTechPool); setSelectedQuarter('') }}><option value="CORE">核心 18 只</option><option value="BROAD">广义 33 只</option></select><ChevronDown size={15} /></span></label>
        <label><span>报告季度</span><span className="select-field"><select value={displayedQuarter} onChange={(event) => setSelectedQuarter(event.target.value)} disabled={!query.data?.available_quarters.length}>{!query.data?.available_quarters.length && <option value="">暂无季度</option>}{query.data?.available_quarters.map((item) => <option key={quarterKey(item.year, item.quarter)} value={quarterKey(item.year, item.quarter)}>{item.year} Q{item.quarter}</option>)}</select><ChevronDown size={15} /></span></label>
        <label><span>暴露口径</span><span className="select-field"><select value={basis} onChange={(event) => setBasis(event.target.value as 'DIRECT' | 'LOOKTHROUGH')}><option value="DIRECT">直接披露</option><option value="LOOKTHROUGH">穿透口径</option></select><Layers3 size={15} /></span></label>
        <button className="button button-secondary dashboard-refresh" type="button" onClick={() => query.refetch()} disabled={query.isFetching}><RefreshCw size={15} />刷新</button>
      </section>

      {query.isPending && <LoadingPanel label="正在聚合季度地区暴露…" />}
      {query.isError && <ErrorPanel error={query.error} onRetry={() => query.refetch()} />}
      {query.data && (
        <>
          <section className="dashboard-date-strip" aria-label="报告与同步日期">
            <div><span>报告季度</span><strong>{query.data.report_year && query.data.report_quarter ? `${query.data.report_year} Q${query.data.report_quarter}` : '—'}</strong></div>
            <div><span>报告期末</span><strong>{formatDate(query.data.period_end)}</strong></div>
            <div><span>最近同步日期</span><strong>{formatDate(query.data.sync_date)}</strong></div>
            <div><span>暴露口径</span><strong>{basis === 'DIRECT' ? '直接披露' : '穿透'}</strong></div>
          </section>

          <section className="metric-grid dashboard-metric-grid">
            <MetricCard label="地区覆盖基金" value={`${query.data.covered_fund_count}`} detail={`基金池共 ${query.data.fund_count} 只`} icon={Globe2} tone="coral" />
            <MetricCard label="覆盖率" value={query.data.fund_count ? formatPercent(query.data.covered_fund_count / query.data.fund_count * 100, 0) : '—'} detail="有对应口径地区明细" icon={CircleGauge} tone="jade" />
            <MetricCard label="平均披露地区权重" value={formatPercent(averageCoverage(query.data), 1)} detail="不对缺失权重归一化" icon={Layers3} tone="ink" />
            <MetricCard label="缺失覆盖" value={`${query.data.missing_fund_count}`} detail={`配置 ${query.data.configured_fund_count} 只`} icon={MapPinned} tone="gold" />
          </section>

          <section className="panel dashboard-chart-panel" aria-labelledby="region-stack-title">
            <div className="panel-heading"><div><span className="section-kicker">FUND COMPOSITION</span><h2 id="region-stack-title">基金地区构成</h2><p>前四大平均地区单列，其余已披露地区合并；横轴固定为净值占比 0–100%。</p></div><span className="panel-caption">{basis === 'DIRECT' ? '直接披露' : '穿透口径'}</span></div>
            {query.data.funds.length > 0
              ? <EChart option={stackedOption} height={Math.min(820, Math.max(360, query.data.funds.length * 25 + 90))} ariaLabel="基金地区构成堆叠图" />
              : <EmptyPanel compact title="没有地区构成数据" detail="先同步并解析对应季度报告。" />}
          </section>

          <section className="dashboard-two-column">
            <section className="panel dashboard-chart-panel" aria-labelledby="region-average-title">
              <div className="panel-heading"><div><span className="section-kicker">POOL AVERAGE</span><h2 id="region-average-title">基金池平均地区分布</h2><p>分母为有地区数据的基金，不对单只基金缺失权重补齐。</p></div></div>
              {query.data.average_distribution.length > 0
                ? <EChart option={averageOption} height={390} ariaLabel="基金池平均地区分布条形图" />
                : <EmptyPanel compact />}
            </section>

            <section className="panel dashboard-coverage-panel" aria-labelledby="region-missing-title">
              <div className="panel-heading"><div><span className="section-kicker">COVERAGE</span><h2 id="region-missing-title">缺失覆盖</h2><p>缺失基金不会进入地区平均值。</p></div><span className="panel-caption">{query.data.missing_fund_count} 只</span></div>
              {query.data.missing.length === 0
                ? <div className="coverage-complete"><StatusBadge value="READY" label="全部基金已有地区明细" /></div>
                : <div className="data-table-wrap dashboard-table-wrap"><table className="data-table dashboard-table compact-dashboard-table"><thead><tr><th>基金</th><th>缺失原因</th></tr></thead><tbody>{query.data.missing.map((item) => <tr key={item.representative_code}><td><span className="dashboard-fund"><strong>{item.fund_name}</strong><small>{item.representative_code}</small></span></td><td><StatusBadge value={item.reason} label={missingReasonLabels[item.reason]} /></td></tr>)}</tbody></table></div>}
            </section>
          </section>

          <p className="dashboard-risk-note dashboard-risk-note-standalone">地区分布来自基金季度报告及本地穿透计算，反映报告期末而非当前实时持仓。公开披露可能不完整，结果仅供研究，不构成投资建议。</p>
        </>
      )}
    </div>
  )
}
