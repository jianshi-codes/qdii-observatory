import { useQuery } from '@tanstack/react-query'
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  CalendarCheck,
  Check,
  ChevronDown,
  Columns3,
  FileCheck2,
  Layers3,
  Search,
  SlidersHorizontal,
  Sparkles,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { FundSummary, PurchaseLimitSummary } from '../api/types'
import { EmptyPanel, ErrorPanel, LoadingPanel } from '../components/StatePanel'
import { StatusBadge } from '../components/StatusBadge'
import {
  displayText,
  field,
  formatDate,
  formatMoney,
  formatPercent,
  statusLabel,
  techScopeLabel,
  toNumber,
  wrapperLabel,
} from '../lib/format'

type ColumnKey =
  | 'tech_scope'
  | 'equity_nav_pct'
  | 'fund_investment_nav_pct'
  | 'us_country_pct'
  | 'korea_country_pct'
  | 'japan_country_pct'
  | 'hong_kong_country_pct'
  | 'china_country_pct'
  | 'information_technology_pct'
  | 'disclosed_top10_pct'
  | 'latest_nav_return_pct'
  | 'direct_purchase_limit'
  | 'distribution_purchase_limit'
  | 'latest_report_status'
  | 'latest_nav_date'

type SortKey = Exclude<ColumnKey, 'tech_scope' | 'latest_report_status' | 'latest_nav_date'>
type SortDirection = 'asc' | 'desc'

const columns: Array<{ key: ColumnKey; label: string }> = [
  { key: 'tech_scope', label: '科技口径' },
  { key: 'equity_nav_pct', label: '股票仓位' },
  { key: 'fund_investment_nav_pct', label: '基金投资' },
  { key: 'us_country_pct', label: '美国' },
  { key: 'korea_country_pct', label: '韩国' },
  { key: 'japan_country_pct', label: '日本' },
  { key: 'hong_kong_country_pct', label: '香港' },
  { key: 'china_country_pct', label: '中国大陆' },
  { key: 'information_technology_pct', label: '信息技术' },
  { key: 'disclosed_top10_pct', label: '前十大' },
  { key: 'latest_nav_return_pct', label: '最新涨跌幅' },
  { key: 'direct_purchase_limit', label: '直销限额' },
  { key: 'distribution_purchase_limit', label: '代销限额' },
  { key: 'latest_report_status', label: 'Q2 报告' },
  { key: 'latest_nav_date', label: '最新净值日期' },
]

const defaultHiddenColumns = new Set<ColumnKey>([
  'direct_purchase_limit',
  'distribution_purchase_limit',
  'latest_report_status',
])

const defaultVisibleColumns = new Set<ColumnKey>(
  columns.filter((column) => !defaultHiddenColumns.has(column.key)).map((column) => column.key),
)

function fundId(fund: FundSummary): string {
  return String(fund.id ?? fund.representative_code)
}

function signedPercent(value: unknown): string {
  const number = toNumber(value)
  if (number === null) return '—'
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`
}

function returnTone(value: unknown): string {
  const number = toNumber(value)
  if (number === null || number === 0) return ''
  return number > 0 ? 'return-positive' : 'return-negative'
}

function limitSortValue(limit: PurchaseLimitSummary | null | undefined): number | null {
  if (!limit || ['NOT_SOLD', 'NOT_APPLICABLE'].includes(limit.availability_state)) return null
  if (limit.cap_state === 'UNLIMITED') return Number.POSITIVE_INFINITY
  if (limit.cap_state === 'LIMITED') return toNumber(limit.daily_limit_amount)
  return null
}

function sortValue(fund: FundSummary, key: SortKey): number | null {
  if (key === 'direct_purchase_limit') return limitSortValue(fund.direct_purchase_limit)
  if (key === 'distribution_purchase_limit') return limitSortValue(fund.distribution_purchase_limit)
  return toNumber(field(fund, key))
}

function limitLabel(limit: PurchaseLimitSummary): string {
  if (limit.availability_state === 'PAUSED') return '暂停申购'
  if (limit.availability_state === 'NOT_SOLD') return '该渠道未销售'
  if (limit.availability_state === 'NOT_APPLICABLE') return '不适用'
  if (limit.cap_state === 'UNLIMITED') return '不限额'
  if (limit.cap_state === 'LIMITED') {
    const unit = limit.currency === 'CNY' ? '元' : ` ${limit.currency}`
    return `${formatMoney(limit.daily_limit_amount)}${unit}/日`
  }
  return '限额未知'
}

function LimitCell({ limit }: { limit: PurchaseLimitSummary | null | undefined }) {
  if (!limit) return <span className="metric-cell">—</span>
  const content = (
    <>
      <strong>{limitLabel(limit)}</strong>
      <small>{limit.channel_name} · {formatDate(limit.snapshot_date)}</small>
    </>
  )
  return limit.source_url ? (
    <a className="limit-summary" href={limit.source_url} target="_blank" rel="noreferrer">
      {content}
    </a>
  ) : <span className="limit-summary">{content}</span>
}

function SortableHeader({
  columnKey,
  label,
  activeKey,
  direction,
  onSort,
}: {
  columnKey: SortKey
  label: string
  activeKey: SortKey | null
  direction: SortDirection
  onSort: (key: SortKey) => void
}) {
  const active = activeKey === columnKey
  return (
    <th className="numeric" aria-sort={active ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button className={active ? 'sort-button is-active' : 'sort-button'} type="button" onClick={() => onSort(columnKey)}>
        {label}
        {active && (direction === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
      </button>
    </th>
  )
}

export function FundOverviewPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [manager, setManager] = useState('全部基金公司')
  const [category, setCategory] = useState('全部原分类')
  const [selected, setSelected] = useState<string[]>([])
  const [visibleColumns, setVisibleColumns] = useState(defaultVisibleColumns)
  const [sort, setSort] = useState<{ key: SortKey | null; direction: SortDirection }>({
    key: null,
    direction: 'desc',
  })
  const fundsQuery = useQuery({
    queryKey: ['funds'],
    queryFn: ({ signal }) => api.funds(signal),
  })

  const funds = useMemo(() => fundsQuery.data ?? [], [fundsQuery.data])
  const managers = useMemo(
    () => [...new Set(funds.map((fund) => fund.manager_name).filter(Boolean))].sort(),
    [funds],
  )
  const categories = useMemo(
    () => [...new Set(funds.map((fund) => fund.original_category).filter((value): value is string => Boolean(value)))].sort(),
    [funds],
  )
  const filteredFunds = useMemo(() => {
    const term = search.trim().toLowerCase()
    const matches = funds.filter((fund) => {
      const matchesSearch = !term || [fund.canonical_name, fund.representative_code, fund.manager_name]
        .some((value) => String(value ?? '').toLowerCase().includes(term))
      return matchesSearch
        && (manager === '全部基金公司' || fund.manager_name === manager)
        && (category === '全部原分类' || fund.original_category === category)
    })
    if (!sort.key) return matches
    return [...matches].sort((left, right) => {
      const leftValue = sortValue(left, sort.key as SortKey)
      const rightValue = sortValue(right, sort.key as SortKey)
      if (leftValue === null && rightValue === null) return fundId(left).localeCompare(fundId(right))
      if (leftValue === null) return 1
      if (rightValue === null) return -1
      const difference = leftValue - rightValue
      return sort.direction === 'asc' ? difference : -difference
    })
  }, [category, funds, manager, search, sort])

  const parsedReports = funds.filter((fund) => String(field(fund, 'latest_report_status', 'report_status', 'q2_report_status')).toLowerCase() === 'parsed').length
  const latestNav = funds
    .map((fund) => field(fund, 'latest_nav_date'))
    .filter((value): value is string => typeof value === 'string')
    .sort()
    .at(-1)
  const availableTechScopes = new Set(
    funds.map((fund) => field(fund, 'tech_scope')).filter((value) => value && value !== 'UNKNOWN'),
  ).size

  function toggleFund(id: string) {
    setSelected((current) => {
      if (current.includes(id)) return current.filter((item) => item !== id)
      if (current.length >= 5) return current
      return [...current, id]
    })
  }

  function toggleColumn(key: ColumnKey) {
    setVisibleColumns((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function toggleSort(key: SortKey) {
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === 'desc' ? 'asc' : 'desc',
    }))
  }

  function openComparison() {
    if (selected.length < 2) return
    navigate(`/compare?ids=${selected.map(encodeURIComponent).join(',')}`)
  }

  const visible = (key: ColumnKey) => visibleColumns.has(key)

  return (
    <div className="page-stack">
      <section className="hero hero-overview">
        <div className="hero-copy">
          <span className="eyebrow"><Sparkles size={14} />最新季度 · 可追溯披露</span>
          <h1>把基金标签，拆成<br /><em>看得见的暴露。</em></h1>
          <p>从基金合同、份额、季度报告到每日净值，沿着证据链查看用户导入的 QDII universe，而不是依赖单一分类标签。</p>
        </div>
        <div className="hero-stats" aria-label="基金数据概况">
          <div className="hero-stat hero-stat-primary"><Layers3 size={19} /><span>用户基金</span><strong>{fundsQuery.isSuccess ? funds.length : '—'}</strong><small>只主基金合同</small></div>
          <div className="hero-stat"><FileCheck2 size={19} /><span>报告已解析</span><strong>{fundsQuery.isSuccess ? parsedReports : '—'}</strong><small>其余状态不静默</small></div>
          <div className="hero-stat"><CalendarCheck size={19} /><span>最新净值</span><strong className="stat-date">{fundsQuery.isSuccess ? formatDate(latestNav) : '—'}</strong><small>{availableTechScopes} 类已识别 tech scope</small></div>
        </div>
      </section>

      <section className="content-section" aria-labelledby="fund-list-title">
        <div className="section-heading">
          <div>
            <span className="section-kicker">UNIVERSE</span>
            <h2 id="fund-list-title">基金总览</h2>
            <p>国家暴露采用最新报告 direct 口径；数值为空表示尚未披露或尚未解析，不做估算补齐。</p>
          </div>
          <div className="selection-summary">
            <span>已选 <strong>{selected.length}</strong> / 5</span>
            <button className="button button-primary" type="button" disabled={selected.length < 2} onClick={openComparison}>
              对比所选<ArrowRight size={16} />
            </button>
          </div>
        </div>

        <div className="filter-bar">
          <label className="search-field">
            <Search size={17} /><span className="sr-only">搜索基金</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索名称、代码或基金公司" />
          </label>
          <label className="select-field">
            <span className="sr-only">筛选基金公司</span>
            <select value={manager} onChange={(event) => setManager(event.target.value)}>
              <option>全部基金公司</option>{managers.map((item) => <option key={item}>{item}</option>)}
            </select><ChevronDown size={15} />
          </label>
          <label className="select-field">
            <span className="sr-only">筛选原分类</span>
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option>全部原分类</option>{categories.map((item) => <option key={item}>{item}</option>)}
            </select><ChevronDown size={15} />
          </label>
          <details className="column-picker">
            <summary><Columns3 size={15} />显示字段 <span>{visibleColumns.size}</span></summary>
            <div className="column-picker-menu">
              {columns.map((column) => (
                <label key={column.key}>
                  <input type="checkbox" checked={visible(column.key)} onChange={() => toggleColumn(column.key)} />
                  <span>{column.label}</span>
                </label>
              ))}
            </div>
          </details>
          <span className="result-count"><SlidersHorizontal size={15} />{filteredFunds.length} 只结果</span>
        </div>

        {fundsQuery.isPending && <LoadingPanel label="正在载入基金 universe…" />}
        {fundsQuery.isError && <ErrorPanel error={fundsQuery.error} onRetry={() => fundsQuery.refetch()} />}
        {fundsQuery.isSuccess && funds.length === 0 && <EmptyPanel title="基金 universe 尚未导入" detail="请到数据运维页从公开信息选择基金或输入六位代码；观察台不会使用演示基金替代真实结果。" />}
        {fundsQuery.isSuccess && funds.length > 0 && filteredFunds.length === 0 && <EmptyPanel title="没有匹配的基金" detail="调整搜索词或筛选条件后再试。" compact />}
        {fundsQuery.isSuccess && filteredFunds.length > 0 && (
          <div className="data-table-wrap">
            <table className="data-table fund-table">
              <thead>
                <tr>
                  <th className="check-column"><span className="sr-only">选择</span></th>
                  <th>基金 / 基金公司</th>
                  {visible('tech_scope') && <th>科技口径</th>}
                  {visible('equity_nav_pct') && <SortableHeader columnKey="equity_nav_pct" label="股票仓位" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />}
                  {visible('fund_investment_nav_pct') && <SortableHeader columnKey="fund_investment_nav_pct" label="基金投资" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />}
                  {visible('us_country_pct') && <SortableHeader columnKey="us_country_pct" label="美国" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />}
                  {visible('korea_country_pct') && <SortableHeader columnKey="korea_country_pct" label="韩国" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />}
                  {visible('japan_country_pct') && <SortableHeader columnKey="japan_country_pct" label="日本" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />}
                  {visible('hong_kong_country_pct') && <SortableHeader columnKey="hong_kong_country_pct" label="香港" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />}
                  {visible('china_country_pct') && <SortableHeader columnKey="china_country_pct" label="中国大陆" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />}
                  {visible('information_technology_pct') && <SortableHeader columnKey="information_technology_pct" label="信息技术" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />}
                  {visible('disclosed_top10_pct') && <SortableHeader columnKey="disclosed_top10_pct" label="前十大" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />}
                  {visible('latest_nav_return_pct') && <SortableHeader columnKey="latest_nav_return_pct" label="最新涨跌幅" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />}
                  {visible('direct_purchase_limit') && <SortableHeader columnKey="direct_purchase_limit" label="直销限额" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />}
                  {visible('distribution_purchase_limit') && <SortableHeader columnKey="distribution_purchase_limit" label="代销限额" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />}
                  {visible('latest_report_status') && <th>Q2 报告</th>}
                  {visible('latest_nav_date') && <th>最新净值日期</th>}
                  <th><span className="sr-only">打开详情</span></th>
                </tr>
              </thead>
              <tbody>
                {filteredFunds.map((fund) => {
                  const id = fundId(fund)
                  const checked = selected.includes(id)
                  const disabled = !checked && selected.length >= 5
                  return (
                    <tr key={id}>
                      <td className="check-column"><button type="button" className={checked ? 'row-check is-checked' : 'row-check'} aria-label={`${checked ? '取消选择' : '选择'} ${fund.canonical_name}`} aria-pressed={checked} disabled={disabled} onClick={() => toggleFund(id)}>{checked && <Check size={13} />}</button></td>
                      <td className="fund-column"><Link className="fund-identity" to={`/funds/${encodeURIComponent(id)}`}><strong>{displayText(fund.canonical_name, '未命名基金')}</strong><span><code>{fund.representative_code}</code>{fund.manager_name}</span></Link></td>
                      {visible('tech_scope') && <td className="scope-column"><span className="scope-label">{techScopeLabel(field(fund, 'tech_scope'))}</span><small className="table-subline">{wrapperLabel(field(fund, 'wrapper_type'))} · {displayText(fund.original_category, '未分类')}</small></td>}
                      {visible('equity_nav_pct') && <td className="numeric metric-cell">{formatPercent(field(fund, 'equity_nav_pct'))}</td>}
                      {visible('fund_investment_nav_pct') && <td className="numeric metric-cell">{formatPercent(field(fund, 'fund_investment_nav_pct'))}</td>}
                      {visible('us_country_pct') && <td className="numeric metric-cell">{formatPercent(field(fund, 'us_country_pct'))}</td>}
                      {visible('korea_country_pct') && <td className="numeric metric-cell">{formatPercent(field(fund, 'korea_country_pct'))}</td>}
                      {visible('japan_country_pct') && <td className="numeric metric-cell">{formatPercent(field(fund, 'japan_country_pct'))}</td>}
                      {visible('hong_kong_country_pct') && <td className="numeric metric-cell">{formatPercent(field(fund, 'hong_kong_country_pct'))}</td>}
                      {visible('china_country_pct') && <td className="numeric metric-cell">{formatPercent(field(fund, 'china_country_pct'))}</td>}
                      {visible('information_technology_pct') && <td className="numeric metric-cell">{formatPercent(field(fund, 'information_technology_pct'))}</td>}
                      {visible('disclosed_top10_pct') && <td className="numeric metric-cell">{formatPercent(field(fund, 'disclosed_top10_pct'))}</td>}
                      {visible('latest_nav_return_pct') && <td className={`numeric metric-cell ${returnTone(field(fund, 'latest_nav_return_pct'))}`}>{signedPercent(field(fund, 'latest_nav_return_pct'))}</td>}
                      {visible('direct_purchase_limit') && <td><LimitCell limit={fund.direct_purchase_limit} /></td>}
                      {visible('distribution_purchase_limit') && <td><LimitCell limit={fund.distribution_purchase_limit} /></td>}
                      {visible('latest_report_status') && <td><StatusBadge value={field(fund, 'latest_report_status', 'report_status', 'q2_report_status')} /></td>}
                      {visible('latest_nav_date') && <td><span className="date-cell">{formatDate(field(fund, 'latest_nav_date'))}</span></td>}
                      <td><Link className="icon-link" to={`/funds/${encodeURIComponent(id)}`} aria-label={`查看 ${fund.canonical_name} 详情`}><ArrowRight size={17} /></Link></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {selected.length >= 5 && <p className="inline-note">已达到 5 只对比上限；取消一只后可重新选择。</p>}
        {fundsQuery.isSuccess && funds.length > 0 && <p className="table-footnote">涨跌幅优先采用基金公司公布值，缺失时使用相邻净值计算值；限额为代表份额最新日快照。报告状态“{statusLabel('valid_empty')}”只代表报告明确披露空表。</p>}
      </section>
    </div>
  )
}
