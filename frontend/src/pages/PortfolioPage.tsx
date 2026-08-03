import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown,
  ArrowUp,
  CalendarClock,
  CircleDollarSign,
  Download,
  FileCheck2,
  Landmark,
  ReceiptText,
  RefreshCw,
  Upload,
  WalletCards,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type {
  PortfolioCurrencySummary,
  PortfolioImportPositionPreview,
  PortfolioPosition,
} from '../api/types'
import { EmptyPanel, ErrorPanel, LoadingPanel } from '../components/StatePanel'
import { formatDate, formatPercent, toNumber } from '../lib/format'

function currencySymbol(currency: string): string {
  return currency === 'CNY' ? '¥' : currency === 'USD' ? '$' : `${currency} `
}

function money(value: unknown, currency: string): string {
  const number = toNumber(value)
  if (number === null) return '—'
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(number)
}

function signedMoney(value: unknown, currency: string): string {
  const number = toNumber(value)
  if (number === null) return '—'
  return `${number > 0 ? '+' : ''}${money(number, currency)}`
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

function summaryFor(
  summaries: PortfolioCurrencySummary[],
  currency: string,
): PortfolioCurrencySummary | undefined {
  return summaries.find((summary) => summary.currency === currency)
}

function feeLabel(position: PortfolioPosition): string {
  const value = position.fees.platform_purchase_fee_pct
  return value === null ? '待补充' : formatPercent(value, 2)
}

function operatingFeeLabel(position: PortfolioPosition): string {
  const management = formatPercent(position.fees.management_fee_pct_annual, 2)
  const custody = formatPercent(position.fees.custody_fee_pct_annual, 2)
  return `管理 ${management} · 托管 ${custody}`
}

async function fileBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  }
  return btoa(binary)
}

function universeAction(item: PortfolioImportPositionPreview): string {
  if (item.universe_action === 'ADD') return '新增到 universe'
  if (item.universe_action === 'RESTORE') return '从归档恢复'
  return '已在 universe'
}

function PortfolioImportPanel({ templateUrl }: { templateUrl: string }) {
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [contentBase64, setContentBase64] = useState('')
  const previewMutation = useMutation({
    mutationFn: async (selected: File) => {
      const encoded = await fileBase64(selected)
      setContentBase64(encoded)
      return api.previewPortfolioImport(selected.name, encoded)
    },
  })
  const confirmMutation = useMutation({
    mutationFn: () => {
      if (!file || !contentBase64 || !previewMutation.data) {
        throw new Error('请先预览持仓文件')
      }
      return api.confirmPortfolioImport(
        file.name,
        contentBase64,
        previewMutation.data.file_digest,
      )
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['portfolio'] }),
        queryClient.invalidateQueries({ queryKey: ['funds'] }),
        queryClient.invalidateQueries({ queryKey: ['data-preparation-status'] }),
      ])
    },
  })
  const preview = previewMutation.data

  return (
    <section className="panel portfolio-import-panel" aria-labelledby="portfolio-import-title">
      <div className="panel-heading">
        <div>
          <span className="section-kicker">LOCAL IMPORT</span>
          <h2 id="portfolio-import-title">导入本地持仓</h2>
          <p>先预览校验，再确认写入。基金会自动加入或恢复到 active universe；缺少净值时确认阶段会先补齐。</p>
        </div>
        <a className="button button-secondary" href={templateUrl} download>
          <Download size={15} />下载 XLSX 模板
        </a>
      </div>
      <div className="portfolio-import-controls">
        <label className="portfolio-file-picker" htmlFor="portfolio-import-file">
          <Upload size={17} />
          <span>{file?.name ?? '选择填写后的 XLSX 文件'}</span>
          <input
            id="portfolio-import-file"
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(event) => {
              const selected = event.target.files?.[0] ?? null
              setFile(selected)
              setContentBase64('')
              previewMutation.reset()
              confirmMutation.reset()
            }}
          />
        </label>
        <button
          className="button button-primary"
          type="button"
          disabled={!file || previewMutation.isPending}
          onClick={() => file && previewMutation.mutate(file)}
        >
          <FileCheck2 size={15} />{previewMutation.isPending ? '正在校验…' : '预览并校验'}
        </button>
      </div>

      {previewMutation.isError && <ErrorPanel compact error={previewMutation.error} />}
      {preview && (
        <div className="portfolio-import-preview">
          <div className="portfolio-import-summary" aria-label="导入预览摘要">
            <span>持仓 <strong>{preview.summary.position_count}</strong></span>
            <span>现金流 <strong>{preview.summary.cash_flow_count}</strong></span>
            <span>新增 / 更新 <strong>{preview.summary.positions_to_add} / {preview.summary.positions_to_update}</strong></span>
            <span>universe 新增 / 恢复 <strong>{preview.summary.universe_to_add} / {preview.summary.universe_to_restore}</strong></span>
            <span>需补净值 <strong>{preview.summary.nav_to_sync}</strong></span>
          </div>
          {preview.errors.length > 0 && (
            <details className="portfolio-import-errors" open>
              <summary>发现 {preview.errors.length} 个问题，修正后重新预览</summary>
              <ul>
                {preview.errors.map((error, index) => (
                  <li key={`${error.sheet}-${error.row}-${error.code}-${index}`}>
                    <code>{error.code}</code>
                    <span>{error.sheet}第 {error.row} 行：{error.message}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {preview.positions.length > 0 && (
            <div className="data-table-wrap">
              <table className="data-table portfolio-import-table">
                <thead><tr><th>基金</th><th>平台 / 快照</th><th>持仓动作</th><th>universe</th><th>净值</th></tr></thead>
                <tbody>
                  {preview.positions.map((item) => (
                    <tr key={`${item.platform}-${item.share_code}`}>
                      <td><strong>{item.fund_name}</strong><small><code>{item.share_code}</code>{item.manager_name}</small></td>
                      <td>{item.platform}<small>{formatDate(item.snapshot_date)} · {item.currency}</small></td>
                      <td>{item.position_action === 'ADD' ? '新增持仓' : '更新持仓'}</td>
                      <td>{universeAction(item)}</td>
                      <td>{item.nav_action === 'SYNC' ? '确认时补齐' : '已有锚点'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="portfolio-import-confirm">
            <span>{preview.valid ? '校验通过；确认后才会写入数据库。' : '当前文件不会写入数据库。'}</span>
            <button
              className="button button-primary"
              type="button"
              disabled={!preview.valid || confirmMutation.isPending}
              onClick={() => confirmMutation.mutate()}
            >
              {confirmMutation.isPending ? '正在加入基金并写入…' : '确认导入'}
            </button>
          </div>
        </div>
      )}
      {confirmMutation.isError && <ErrorPanel compact error={confirmMutation.error} />}
      {confirmMutation.data && (
        <div className="portfolio-import-success" role="status">
          <strong>导入完成</strong>
          <span>写入 {confirmMutation.data.positions_written} 个持仓、{confirmMutation.data.cash_flows_written} 条现金流；页面已自动刷新。</span>
        </div>
      )}
    </section>
  )
}

type SortKey =
  | 'estimated_market_value_cny'
  | 'latest_daily_return_pct'
  | 'estimated_daily_profit_amount_cny'
  | 'estimated_profit_amount_cny'
type SortDirection = 'asc' | 'desc'

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

export function PortfolioPage() {
  const [sort, setSort] = useState<{ key: SortKey | null; direction: SortDirection }>({
    key: null,
    direction: 'desc',
  })
  const capabilityQuery = useQuery({
    queryKey: ['portfolio-capability'],
    queryFn: ({ signal }) => api.portfolioCapability(signal),
  })
  const portfolioEnabled = capabilityQuery.data?.enabled === true
  const portfolioQuery = useQuery({
    queryKey: ['portfolio'],
    queryFn: ({ signal }) => api.portfolio(signal),
    enabled: portfolioEnabled,
  })
  const portfolio = portfolioQuery.data
  const positions = useMemo(() => portfolio?.positions ?? [], [portfolio])
  const cny = summaryFor(portfolio?.currency_summaries ?? [], 'CNY')
  const usd = summaryFor(portfolio?.currency_summaries ?? [], 'USD')
  const recurringCount = positions.filter((position) => position.recurring_plan).length
  const sortedPositions = useMemo(() => {
    if (!sort.key) return positions
    return [...positions].sort((left, right) => {
      const leftValue = toNumber(left[sort.key as SortKey])
      const rightValue = toNumber(right[sort.key as SortKey])
      if (leftValue === null && rightValue === null) return left.share_code.localeCompare(right.share_code)
      if (leftValue === null) return 1
      if (rightValue === null) return -1
      const difference = leftValue - rightValue
      return sort.direction === 'asc' ? difference : -difference
    })
  }, [positions, sort])

  function toggleSort(key: SortKey) {
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === 'desc' ? 'asc' : 'desc',
    }))
  }

  return (
    <div className="page-stack">
      <section className="page-intro portfolio-intro">
        <div className="detail-title">
          <span className="code-chip"><WalletCards size={30} /></span>
          <div>
            <span className="eyebrow">LOCAL PORTFOLIO · 用户快照</span>
            <h1>我的持仓</h1>
            <p>以平台快照为锚点，使用已归档的份额净值更新参考市值；原币种分别保留，另提供人民币参考折算。</p>
          </div>
        </div>
        <div className="as-of-card">
          <RefreshCw size={18} />
          <span>最新净值日</span>
          <strong>{formatDate(portfolio?.latest_nav_date)}</strong>
          <small>运行 make sync-qdii-daily 后自动刷新；定投计划不会自动记为已成交。</small>
        </div>
      </section>

      {capabilityQuery.isPending && <LoadingPanel label="正在确认本地持仓能力…" />}
      {capabilityQuery.isError && <ErrorPanel error={capabilityQuery.error} onRetry={() => capabilityQuery.refetch()} />}
      {capabilityQuery.isSuccess && !portfolioEnabled && (
        <EmptyPanel title="本地持仓尚未启用" detail="入口会保持可见；在本机 .env 设置 QDII_ENABLE_PORTFOLIO=true 并重启后即可导入，项目不会连接真实账户。" />
      )}
      {portfolioEnabled && (
        <PortfolioImportPanel
          templateUrl={capabilityQuery.data?.template_url ?? '/templates/portfolio-import-template.xlsx'}
        />
      )}
      {portfolioEnabled && portfolioQuery.isPending && <LoadingPanel label="正在读取本地持仓…" />}
      {portfolioQuery.isError && <ErrorPanel error={portfolioQuery.error} onRetry={() => portfolioQuery.refetch()} />}
      {portfolioQuery.isSuccess && positions.length === 0 && (
        <EmptyPanel title="尚未导入本地持仓" detail="下载模板并填写后，在上方预览校验；只有点击“确认导入”才会写入本地数据库。" />
      )}

      {portfolioQuery.isSuccess && positions.length > 0 && (
        <>
          <section className="metric-grid portfolio-metric-grid" aria-label="持仓概况">
            <article className="metric-card metric-coral portfolio-currency-card">
              <div className="metric-card-top"><span>人民币持仓</span><WalletCards size={17} /></div>
              <strong>{money(cny?.estimated_market_value, 'CNY')}</strong>
              <div className="portfolio-card-profit">
                <span>{cny?.position_count ?? 0} 个份额 · 持有收益 / 收益率</span>
                <div className="portfolio-profit-value">
                  <b className={returnTone(cny?.estimated_profit_amount)}>{signedMoney(cny?.estimated_profit_amount, 'CNY')}</b>
                  <em className={returnTone(cny?.estimated_return_pct)}>{signedPercent(cny?.estimated_return_pct)}</em>
                </div>
              </div>
            </article>
            <article className="metric-card metric-jade portfolio-currency-card">
              <div className="metric-card-top"><span>美元持仓</span><Landmark size={17} /></div>
              <strong>{money(usd?.estimated_market_value, 'USD')}</strong>
              <div className="portfolio-card-profit">
                <span>{usd?.position_count ?? 0} 个份额 · 持有收益 / 收益率</span>
                <div className="portfolio-profit-value">
                  <b className={returnTone(usd?.estimated_profit_amount)}>{signedMoney(usd?.estimated_profit_amount, 'USD')}</b>
                  <em className={returnTone(usd?.estimated_return_pct)}>{signedPercent(usd?.estimated_return_pct)}</em>
                </div>
              </div>
            </article>
            <article className="metric-card portfolio-total-card">
              <div className="metric-card-top"><span>折算人民币总计</span><CircleDollarSign size={17} /></div>
              <strong>{money(portfolio?.converted_summary?.estimated_market_value, 'CNY')}</strong>
              <div className="portfolio-card-profit">
                <span>总持有收益 / 收益率</span>
                <div className="portfolio-profit-value">
                  <b className={returnTone(portfolio?.converted_summary?.estimated_profit_amount)}>{signedMoney(portfolio?.converted_summary?.estimated_profit_amount, 'CNY')}</b>
                  <em className={returnTone(portfolio?.converted_summary?.estimated_return_pct)}>{signedPercent(portfolio?.converted_summary?.estimated_return_pct)}</em>
                </div>
              </div>
              {portfolio?.converted_summary?.source_url ? (
                <a className="portfolio-fx-source" href={portfolio.converted_summary.source_url} target="_blank" rel="noreferrer">
                  USD/CNY {toNumber(portfolio.converted_summary.usd_cny_rate)?.toFixed(6)} · {formatDate(portfolio.converted_summary.rate_date)} · ECB 参考
                </a>
              ) : <small className="portfolio-fx-source">等待同步 USD/CNY 参考汇率</small>}
            </article>
            <article className="metric-card metric-gold portfolio-daily-card">
              <div className="metric-card-top"><span>最新日收益</span><CircleDollarSign size={17} /></div>
              <div className="portfolio-dual-values">
                <span><small>CNY</small><b className={returnTone(cny?.estimated_daily_profit_amount)}>{signedMoney(cny?.estimated_daily_profit_amount, 'CNY')}</b><em className={returnTone(cny?.estimated_daily_return_pct)}>{signedPercent(cny?.estimated_daily_return_pct)}</em></span>
                <span><small>USD</small><b className={returnTone(usd?.estimated_daily_profit_amount)}>{signedMoney(usd?.estimated_daily_profit_amount, 'USD')}</b><em className={returnTone(usd?.estimated_daily_return_pct)}>{signedPercent(usd?.estimated_daily_return_pct)}</em></span>
                <span><small>折合</small><b className={returnTone(portfolio?.converted_summary?.estimated_daily_profit_amount)}>{signedMoney(portfolio?.converted_summary?.estimated_daily_profit_amount, 'CNY')}</b><em className={returnTone(portfolio?.converted_summary?.estimated_daily_return_pct)}>{signedPercent(portfolio?.converted_summary?.estimated_daily_return_pct)}</em></span>
              </div>
              <small>按各份额最新两期净值估算</small>
            </article>
            <article className="metric-card portfolio-recurring-card">
              <div className="metric-card-top"><span>每日定投计划</span><CalendarClock size={17} /></div>
              <strong>{`${currencySymbol('CNY')}${toNumber(cny?.recurring_gross_amount)?.toFixed(2) ?? '0.00'}`}</strong>
              <small>{recurringCount} 个计划 · 实际投入 {money(cny?.recurring_net_amount, 'CNY')} · 到账 {formatPercent(cny?.recurring_net_pct, 2)}</small>
            </article>
          </section>

          <section className="panel portfolio-panel" aria-labelledby="portfolio-table-title">
            <div className="panel-heading">
              <div>
                <span className="section-kicker">POSITIONS</span>
                <h2 id="portfolio-table-title">持仓明细</h2>
                <p>市值与收益均保留原币种；管理费和托管费已体现在净值中，不会在这里再次扣减。</p>
              </div>
              <span className="portfolio-count">{positions.length} 个份额</span>
            </div>
            <div className="data-table-wrap">
              <table className="data-table portfolio-table">
                <thead>
                  <tr>
                    <th>基金 / 平台</th>
                    <SortableHeader columnKey="estimated_market_value_cny" label="参考市值" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />
                    <SortableHeader columnKey="latest_daily_return_pct" label="最新涨跌" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />
                    <SortableHeader columnKey="estimated_daily_profit_amount_cny" label="最新日收益" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />
                    <SortableHeader columnKey="estimated_profit_amount_cny" label="持有收益" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />
                    <th className="numeric">累计收益 / 分红</th>
                    <th>每日定投</th>
                    <th>平台手续费</th>
                    <th>年运作费率</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedPositions.map((position) => (
                    <tr key={String(position.id)}>
                      <td className="fund-column">
                        <Link className="fund-identity" to={`/funds/${position.fund_id}`}>
                          <strong>{position.canonical_name}</strong>
                          <span><code>{position.share_code}</code>{position.platform} · {position.currency}</span>
                        </Link>
                        {position.data_quality_note && <small className="portfolio-note">{position.data_quality_note}</small>}
                      </td>
                      <td className="numeric metric-cell">
                        {money(position.estimated_market_value, position.currency)}
                        <small className="table-subline">快照 {money(position.reported_market_value, position.currency)}</small>
                        {position.currency === 'USD' && <small className="table-subline">折合 {money(position.estimated_market_value_cny, 'CNY')}</small>}
                      </td>
                      <td className={`numeric metric-cell ${returnTone(position.latest_daily_return_pct)}`}>
                        {signedPercent(position.latest_daily_return_pct)}
                      </td>
                      <td className={`numeric metric-cell ${returnTone(position.estimated_daily_profit_amount)}`}>
                        {signedMoney(position.estimated_daily_profit_amount, position.currency)}
                        {position.currency === 'USD' && <small className="table-subline">折合 {signedMoney(position.estimated_daily_profit_amount_cny, 'CNY')}</small>}
                      </td>
                      <td className={`numeric metric-cell ${returnTone(position.estimated_profit_amount)}`}>
                        {signedMoney(position.estimated_profit_amount, position.currency)}
                        <small className="table-subline">平台收益率 {signedPercent(position.estimated_return_pct)}</small>
                        {position.currency === 'USD' && <small className="table-subline">折合 {signedMoney(position.estimated_profit_amount_cny, 'CNY')}</small>}
                      </td>
                      <td className={`numeric metric-cell ${returnTone(position.estimated_cumulative_profit_amount)}`}>
                        {signedMoney(position.estimated_cumulative_profit_amount, position.currency)}
                        {position.cash_flows.length > 0 && (
                          <details className="cash-flow-details">
                            <summary>分红 {position.cash_flows.length} 笔 · {money(position.cash_dividend_total, position.currency)}</summary>
                            <div>
                              {position.cash_flows.map((flow, index) => (
                                <span key={`${flow.occurred_year}-${index}`}>
                                  {flow.occurred_on ? formatDate(flow.occurred_on) : `${flow.occurred_year} 年（日期待补）`}
                                  <strong>{money(flow.amount, flow.currency)}</strong>
                                </span>
                              ))}
                            </div>
                          </details>
                        )}
                      </td>
                      <td>
                        {position.recurring_plan ? (
                          <span className="portfolio-plan">
                            <strong>{money(position.recurring_plan.gross_amount, position.currency)}</strong>
                            <small>实际 {money(position.recurring_plan.net_amount, position.currency)}</small>
                          </span>
                        ) : '—'}
                      </td>
                      <td>
                        <span className="portfolio-fee">
                          <strong>{feeLabel(position)}</strong>
                          <small>{position.fees.platform_purchase_fee_pct === null ? '可在本地 JSON 补充' : '用户提供的平台口径'}</small>
                        </span>
                      </td>
                      <td>
                        <span className="portfolio-fee">
                          <strong>{operatingFeeLabel(position)}</strong>
                          {position.fees.source_url ? (
                            <a href={position.fees.source_url} target="_blank" rel="noreferrer">参考来源 · {formatDate(position.fees.snapshot_date)}</a>
                          ) : <small>费率待同步</small>}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="panel-note"><ReceiptText size={13} /> 参考市值是净值估算，不是平台账户直连结果；申购确认、分红、赎回或定投成交后，请重新导入平台快照。</p>
          </section>
        </>
      )}
    </div>
  )
}
