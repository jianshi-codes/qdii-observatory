import { useQuery } from '@tanstack/react-query'
import type { EChartsOption, SeriesOption } from 'echarts'
import {
  ArrowUpRight,
  Check,
  Layers3,
  Search,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  X,
} from 'lucide-react'
import { useMemo, useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router'
import { api } from '../api/client'
import type { ComparePayload, FundSummary } from '../api/types'
import { EChart } from '../components/EChart'
import { EmptyPanel, ErrorPanel, LoadingPanel } from '../components/StatePanel'
import { displayText, field, formatPercent, techScopeLabel, toNumber, wrapperLabel } from '../lib/format'

function idOf(fund: FundSummary): string {
  return String(fund.id ?? fund.representative_code)
}

function recordId(record: Record<string, unknown>): string {
  return String(record.fund_id ?? record.fund_contract_id ?? record.id ?? '')
}

function recordName(record: Record<string, unknown>): string {
  return displayText(
    record.normalized_name
      ?? record.name_normalized
      ?? record.country_normalized
      ?? record.industry_normalized
      ?? record.name
      ?? record.label,
    '未归一化',
  )
}

function exposureCompareOption(
  records: Record<string, unknown>[],
  selectedFunds: FundSummary[],
): EChartsOption {
  const categories = [...new Set(records.map(recordName))]
  const visible = categories
    .map((name) => ({
      name,
      max: Math.max(...selectedFunds.map((fund) => {
        const match = records.find((record) => recordId(record) === idOf(fund) && recordName(record) === name)
        return toNumber(match?.nav_pct ?? match?.value ?? match?.lookthrough_nav_pct) ?? 0
      })),
    }))
    .sort((a, b) => b.max - a.max)
    .slice(0, 12)
    .reverse()

  return {
    color: ['#24364b', '#e76f51', '#268a7b', '#c69136', '#846c9b'],
    grid: { top: 48, right: 20, bottom: 30, left: 120 },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (value) => `${Number(value).toFixed(2)}%` },
    legend: { type: 'scroll', top: 0, left: 0, textStyle: { color: '#56616f', fontSize: 11 } },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#7b838c', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#ece9e2' } },
    },
    yAxis: {
      type: 'category',
      data: visible.map((item) => item.name),
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { color: '#303944', width: 108, overflow: 'truncate' },
    },
    series: selectedFunds.map((fund) => ({
      type: 'bar',
      name: fund.representative_code,
      barMaxWidth: 10,
      data: visible.map(({ name }) => {
        const match = records.find((record) => recordId(record) === idOf(fund) && recordName(record) === name)
        return toNumber(match?.nav_pct ?? match?.value ?? match?.lookthrough_nav_pct)
      }),
    })),
  }
}

function navCompareOption(records: Record<string, unknown>[], selectedFunds: FundSummary[]): EChartsOption {
  const flat: Record<string, unknown>[] = []
  for (const record of records) {
    const nestedItems = Array.isArray(record.items) ? record.items : record.points
    if (Array.isArray(nestedItems)) {
      for (const point of nestedItems as Record<string, unknown>[]) {
        flat.push({ ...point, fund_id: record.fund_id ?? record.fund_contract_id })
      }
    } else {
      flat.push(record)
    }
  }

  const series = selectedFunds.map((fund): SeriesOption => {
    const points = flat
      .filter((record) => recordId(record) === idOf(fund))
      .sort((a, b) => String(a.nav_date ?? a.date).localeCompare(String(b.nav_date ?? b.date)))
    const firstValue = points.map((point) => toNumber(point.unit_nav ?? point.value)).find((value) => value !== null) ?? null
    return {
      name: fund.representative_code,
      type: 'line',
      showSymbol: false,
      sampling: 'lttb',
      data: points.map((point) => {
        const value = toNumber(point.unit_nav ?? point.value)
        return [String(point.nav_date ?? point.date), value !== null && firstValue ? value / firstValue * 100 : null]
      }),
    }
  })

  return {
    color: ['#24364b', '#e76f51', '#268a7b', '#c69136', '#846c9b'],
    grid: { top: 42, right: 18, bottom: 36, left: 56 },
    tooltip: { trigger: 'axis', valueFormatter: (value) => `${Number(value).toFixed(2)}` },
    legend: { type: 'scroll', top: 0, left: 0, textStyle: { color: '#56616f', fontSize: 11 } },
    xAxis: { type: 'time', axisLabel: { color: '#7b838c', hideOverlap: true } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: '#7b838c' }, splitLine: { lineStyle: { color: '#ece9e2' } } },
    dataZoom: [{ type: 'inside' }],
    series,
  }
}

function exposureRecords(payload: ComparePayload, kind: 'country' | 'industry'): Record<string, unknown>[] {
  const records: Record<string, unknown>[] = []
  for (const group of payload.exposures ?? []) {
    const items = group[kind]
    if (!Array.isArray(items)) continue
    for (const item of items as Record<string, unknown>[]) {
      records.push({ ...item, fund_id: group.fund_id })
    }
  }
  return records
}

function overlapRecords(payload: ComparePayload, funds: FundSummary[]): Record<string, unknown>[] {
  const codeFor = (id: unknown) => funds.find((fund) => idOf(fund) === String(id))?.representative_code ?? String(id ?? '—')
  const records: Record<string, unknown>[] = []
  for (const group of payload.holding_overlaps ?? []) {
    if (!Array.isArray(group.items)) continue
    for (const item of group.items as Record<string, unknown>[]) {
      records.push({
        ...item,
        fund_pair: `${codeFor(group.left_fund_id)} × ${codeFor(group.right_fund_id)}`,
      })
    }
  }
  return records
}

function correlationRecords(payload: ComparePayload, funds: FundSummary[]): Record<string, unknown>[] {
  const codeFor = (id: unknown) => funds.find((fund) => idOf(fund) === String(id))?.representative_code ?? String(id ?? '—')
  return (payload.return_correlations ?? []).map((record) => ({
    ...record,
    left_fund_code: codeFor(record.left_fund_id),
    right_fund_code: codeFor(record.right_fund_id),
  }))
}

export function ComparePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const selectedIds = useMemo(
    () => (searchParams.get('ids') ?? '').split(',').filter(Boolean).slice(0, 5),
    [searchParams],
  )
  const fundsQuery = useQuery({
    queryKey: ['funds'],
    queryFn: ({ signal }) => api.funds(signal),
  })
  const selectedFunds = useMemo(
    () => selectedIds
      .map((id) => fundsQuery.data?.find((fund) => idOf(fund) === id))
      .filter((fund): fund is FundSummary => Boolean(fund)),
    [fundsQuery.data, selectedIds],
  )
  const compareQuery = useQuery({
    queryKey: ['compare', selectedIds],
    queryFn: ({ signal }) => api.compare(selectedIds, signal),
    enabled: selectedIds.length >= 2,
  })
  const visibleFunds = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!term) return fundsQuery.data ?? []
    return (fundsQuery.data ?? []).filter((fund) =>
      [fund.canonical_name, fund.representative_code, fund.manager_name]
        .some((value) => String(value ?? '').toLowerCase().includes(term)),
    )
  }, [fundsQuery.data, search])

  function writeSelection(ids: string[]) {
    const next = new URLSearchParams(searchParams)
    if (ids.length) next.set('ids', ids.join(','))
    else next.delete('ids')
    setSearchParams(next, { replace: true })
  }

  function toggle(id: string) {
    if (selectedIds.includes(id)) writeSelection(selectedIds.filter((item) => item !== id))
    else if (selectedIds.length < 5) writeSelection([...selectedIds, id])
  }

  const countryRecords = useMemo(
    () => compareQuery.data ? exposureRecords(compareQuery.data, 'country') : [],
    [compareQuery.data],
  )
  const industryRecords = useMemo(
    () => compareQuery.data ? exposureRecords(compareQuery.data, 'industry') : [],
    [compareQuery.data],
  )
  const navRecords = useMemo(() => compareQuery.data?.nav_series ?? [], [compareQuery.data])
  const overlaps = useMemo(
    () => compareQuery.data ? overlapRecords(compareQuery.data, selectedFunds) : [],
    [compareQuery.data, selectedFunds],
  )
  const correlations = useMemo(
    () => compareQuery.data ? correlationRecords(compareQuery.data, selectedFunds) : [],
    [compareQuery.data, selectedFunds],
  )
  const countryOption = useMemo(() => exposureCompareOption(countryRecords, selectedFunds), [countryRecords, selectedFunds])
  const industryOption = useMemo(() => exposureCompareOption(industryRecords, selectedFunds), [industryRecords, selectedFunds])
  const navOption = useMemo(() => navCompareOption(navRecords, selectedFunds), [navRecords, selectedFunds])

  return (
    <div className="page-stack compare-page">
      <section className="page-intro compare-intro">
        <div>
          <span className="eyebrow"><Sparkles size={14} />SIDE BY SIDE</span>
          <h1>基金对比</h1>
          <p>最多选择 5 只基金，对照穿透暴露、披露持仓与真实净值序列。不同报告时点不会被假装成同一时点。</p>
        </div>
        <div className="compare-counter">
          <strong>{selectedIds.length}</strong><span>/ 5</span><small>已选基金</small>
        </div>
      </section>

      <section className="panel fund-picker" aria-labelledby="fund-picker-title">
        <div className="panel-heading">
          <div><span className="section-kicker">SELECTION</span><h2 id="fund-picker-title">选择基金</h2></div>
          {selectedIds.length > 0 && <button className="text-button" type="button" onClick={() => writeSelection([])}>清空选择</button>}
        </div>
        <label className="search-field search-field-wide">
          <Search size={17} /><span className="sr-only">搜索待对比基金</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="按基金名称、代码或公司筛选" />
        </label>
        {fundsQuery.isPending && <LoadingPanel label="载入可选基金…" />}
        {fundsQuery.isError && <ErrorPanel compact error={fundsQuery.error} onRetry={() => fundsQuery.refetch()} />}
        {fundsQuery.isSuccess && fundsQuery.data.length === 0 && <EmptyPanel compact title="没有可选基金" detail="先导入 universe 后再进行对比。" />}
        {fundsQuery.isSuccess && visibleFunds.length > 0 && (
          <div className="fund-option-strip">
            {visibleFunds.map((fund) => {
              const id = idOf(fund)
              const checked = selectedIds.includes(id)
              return (
                <button
                  type="button"
                  key={id}
                  className={checked ? 'fund-option is-selected' : 'fund-option'}
                  disabled={!checked && selectedIds.length >= 5}
                  onClick={() => toggle(id)}
                >
                  <span className="fund-option-check">{checked ? <Check size={13} /> : <span />}</span>
                  <span><strong>{fund.representative_code}</strong><small>{fund.canonical_name}</small></span>
                </button>
              )
            })}
          </div>
        )}
      </section>

      {selectedFunds.length > 0 && (
        <section className="compare-fund-cards" aria-label="已选基金摘要">
          {selectedFunds.map((fund, index) => (
            <article key={idOf(fund)} style={{ '--fund-index': index } as CSSProperties}>
              <button type="button" aria-label={`移除 ${fund.canonical_name}`} onClick={() => toggle(idOf(fund))}><X size={14} /></button>
              <span>{fund.representative_code}</span>
              <strong>{fund.canonical_name}</strong>
              <small>{techScopeLabel(field(fund, 'tech_scope'))}</small>
              <dl>
                <div><dt>股票</dt><dd>{formatPercent(field(fund, 'equity_nav_pct'))}</dd></div>
                <div><dt>美国</dt><dd>{formatPercent(field(fund, 'us_country_pct'))}</dd></div>
                <div><dt>信息技术</dt><dd>{formatPercent(field(fund, 'information_technology_pct'))}</dd></div>
              </dl>
              <Link to={`/funds/${encodeURIComponent(idOf(fund))}`}>查看详情<ArrowUpRight size={14} /></Link>
            </article>
          ))}
        </section>
      )}

      {selectedIds.length < 2 && (
        <EmptyPanel
          title="再选择至少一只基金"
          detail="对比请求会在选择 2–5 只基金后发出；当前不会加载或生成任何示例曲线。"
          action={<span className="empty-hint"><SlidersHorizontal size={15} />从上方列表选择</span>}
        />
      )}
      {selectedIds.length >= 2 && selectedFunds.length !== selectedIds.length && fundsQuery.isSuccess && (
        <EmptyPanel title="部分基金不存在" detail="URL 中包含不在当前用户 universe 的基金 ID，请重新选择。" icon="warning" />
      )}
      {selectedFunds.length >= 2 && compareQuery.isPending && <LoadingPanel label="正在计算对比数据…" />}
      {selectedFunds.length >= 2 && compareQuery.isError && <ErrorPanel error={compareQuery.error} onRetry={() => compareQuery.refetch()} />}
      {selectedFunds.length >= 2 && compareQuery.isSuccess && (
        <>
          <div className="detail-grid">
            <ComparisonChart title="国家 / 地区暴露" kicker="GEOGRAPHY" records={countryRecords} option={countryOption} ariaLabel="多基金国家暴露对比图" />
            <ComparisonChart title="行业暴露" kicker="SECTORS" records={industryRecords} option={industryOption} ariaLabel="多基金行业暴露对比图" />
          </div>

          <section className="panel chart-panel">
            <div className="panel-heading">
              <div><span className="section-kicker">NORMALIZED NAV</span><h2>净值曲线</h2></div>
              <span className="panel-caption">各序列首个有效值 = 100</span>
            </div>
            {navRecords.length > 0
              ? <EChart option={navOption} height={380} ariaLabel="多基金归一化净值对比图" />
              : <EmptyPanel compact title="对比净值不可用" detail="API 未返回可对齐的真实净值序列。" />}
          </section>

          <div className="detail-grid">
            <CompareRecordTable
              title="重仓股重叠"
              kicker="OVERLAP"
              records={overlaps}
              columns={[
                ['证券', ['security_name', 'security_code']],
                ['基金对', ['fund_pair']],
                ['左侧权重', ['left_nav_pct']],
                ['右侧权重', ['right_nav_pct']],
              ]}
              percentColumns={[2, 3]}
            />
            <CompareRecordTable
              title="收益相关性"
              kicker="CORRELATION"
              records={correlations}
              columns={[
                ['基金 A', ['left_fund_code']],
                ['基金 B', ['right_fund_code']],
                ['共同观测', ['common_observations']],
                ['相关系数', ['correlation', 'value']],
              ]}
            />
          </div>

          <section className="panel compare-channel-panel">
            <div className="panel-heading">
              <div><span className="section-kicker">WRAPPER & CHANNEL</span><h2>Wrapper / 渠道限额入口</h2></div>
              <ShieldAlert size={20} />
            </div>
            <div className="channel-grid">
              {selectedFunds.map((fund) => (
                <article key={idOf(fund)}>
                  <span>{fund.representative_code}</span>
                  <strong>{wrapperLabel(field(fund, 'wrapper_type'))}</strong>
                  <p>每日限额已按份额、渠道和来源归档；进入基金详情查看最新快照。</p>
                </article>
              ))}
            </div>
            <p className="panel-note">对比页不把具名代销渠道扩展成全部代销，也不将未知状态解释为不限额；场内价格与基金净值仍保持不同序列。</p>
          </section>
        </>
      )}
    </div>
  )
}

function ComparisonChart({ title, kicker, records, option, ariaLabel }: {
  title: string
  kicker: string
  records: Record<string, unknown>[]
  option: EChartsOption
  ariaLabel: string
}) {
  return (
    <section className="panel chart-panel">
      <div className="panel-heading"><div><span className="section-kicker">{kicker}</span><h2>{title}</h2></div><Layers3 size={20} /></div>
      {records.length > 0
        ? <EChart option={option} ariaLabel={ariaLabel} />
        : <EmptyPanel compact title={`${title}不可用`} detail="对比 API 未返回这一组真实数据。" />}
    </section>
  )
}

function CompareRecordTable({ title, kicker, records, columns, percentColumns = [] }: {
  title: string
  kicker: string
  records: Record<string, unknown>[]
  columns: [string, string[]][]
  percentColumns?: number[]
}) {
  return (
    <section className="panel">
      <div className="panel-heading"><div><span className="section-kicker">{kicker}</span><h2>{title}</h2></div></div>
      {records.length === 0 ? (
        <EmptyPanel compact title={`${title}不可用`} detail="样本不足或 API 尚未返回该计算结果。" />
      ) : (
        <div className="compact-table-wrap">
          <table className="data-table compact-table">
            <thead><tr>{columns.map(([label]) => <th key={label}>{label}</th>)}</tr></thead>
            <tbody>{records.map((record, index) => (
              <tr key={String(record.id ?? index)}>
                {columns.map(([label, keys], columnIndex) => {
                  const value = keys.map((key) => record[key]).find((item) => item !== undefined && item !== null)
                  return <td key={label}>{percentColumns.includes(columnIndex) ? formatPercent(value) : displayText(value)}</td>
                })}
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </section>
  )
}
