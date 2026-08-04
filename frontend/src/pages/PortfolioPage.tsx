import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowDown,
  ArrowUp,
  CalendarClock,
  CircleDollarSign,
  Download,
  FileCheck2,
  Landmark,
  Layers3,
  Pencil,
  Plus,
  ReceiptText,
  RefreshCw,
  Upload,
  WalletCards,
  X,
} from 'lucide-react'
import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api/client'
import type {
  PortfolioCurrencySummary,
  PortfolioConsistencyPayload,
  PortfolioEditableInput,
  PortfolioImportPositionPreview,
  PortfolioPosition,
  PortfolioPositionCreateInput,
} from '../api/types'
import { EmptyPanel, ErrorPanel, LoadingPanel } from '../components/StatePanel'
import { StatusBadge } from '../components/StatusBadge'
import { formatDate, formatPercent, statusLabel, toNumber } from '../lib/format'

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

function signedPercentagePoints(value: unknown): string {
  const number = toNumber(value)
  if (number === null) return '—'
  return `${number > 0 ? '+' : ''}${number.toFixed(2)} 个百分点`
}

function units(value: unknown): string {
  const number = toNumber(value)
  if (number === null) return '—'
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(number)
}

function returnTone(value: unknown): string {
  const number = toNumber(value)
  if (number === null || number === 0) return ''
  return number > 0 ? 'return-positive' : 'return-negative'
}

function shanghaiDate(value: string | null | undefined): string | null {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return null
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(parsed)
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
          <p>持有份额驱动快照后的估值变化；市值、持有收益和收益率构成同日平台快照基线。基金会自动加入或恢复到 active universe。</p>
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
                <thead><tr><th>基金</th><th>平台 / 快照</th><th className="numeric">持有份额</th><th>持仓动作</th><th>universe</th><th>净值</th></tr></thead>
                <tbody>
                  {preview.positions.map((item) => (
                    <tr key={`${item.platform}-${item.share_code}`}>
                      <td><strong>{item.fund_name}</strong><small><code>{item.share_code}</code>{item.manager_name}</small></td>
                      <td>{item.platform}<small>{formatDate(item.snapshot_date)} · {item.currency}</small></td>
                      <td className="numeric"><strong>{units(item.units)}</strong><small>估值主数据</small></td>
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

type PositionDialogTarget =
  | { kind: 'create' }
  | { kind: 'edit'; position: PortfolioPosition }

function inputValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  const number = toNumber(value)
  return number === null ? String(value) : String(number)
}

function PortfolioPositionDialog({
  target,
  onClose,
  onSaved,
}: {
  target: PositionDialogTarget
  onClose: () => void
  onSaved: () => void
}) {
  const position = target.kind === 'edit' ? target.position : null
  const [shareCode, setShareCode] = useState(position?.share_code ?? '')
  const [platform, setPlatform] = useState(position?.platform ?? '')
  const [snapshotDate, setSnapshotDate] = useState(
    position?.snapshot_date ?? new Date().toISOString().slice(0, 10),
  )
  const [holdingUnits, setHoldingUnits] = useState(inputValue(position?.reported_units))
  const [marketValue, setMarketValue] = useState(inputValue(position?.reported_market_value))
  const [holdingProfit, setHoldingProfit] = useState(inputValue(position?.reported_profit_amount))
  const [holdingReturn, setHoldingReturn] = useState(inputValue(position?.reported_return_pct))
  const [cumulativeProfit, setCumulativeProfit] = useState(
    inputValue(position?.reported_cumulative_profit_amount),
  )
  const [recurringEnabled, setRecurringEnabled] = useState(Boolean(position?.recurring_plan))
  const [recurringGross, setRecurringGross] = useState(
    inputValue(position?.recurring_plan?.gross_amount),
  )
  const [recurringFee, setRecurringFee] = useState(
    inputValue(position?.recurring_plan?.fee_pct ?? 0),
  )
  const [recurringLag, setRecurringLag] = useState(
    String(position?.recurring_plan?.confirmation_lag_days ?? 2),
  )
  const [purchaseFee, setPurchaseFee] = useState(
    inputValue(position?.manual_purchase_fee_pct),
  )
  const [managementFee, setManagementFee] = useState(
    inputValue(position?.manual_management_fee_pct_annual),
  )
  const [custodyFee, setCustodyFee] = useState(
    inputValue(position?.manual_custody_fee_pct_annual),
  )
  const mutation = useMutation({
    mutationFn: (payload: PortfolioEditableInput | PortfolioPositionCreateInput) => (
      target.kind === 'create'
        ? api.createPortfolioPosition(payload as PortfolioPositionCreateInput)
        : api.updatePortfolioPosition(String(target.position.id), payload)
    ),
    onSuccess: onSaved,
  })

  function optionalNumber(value: string): string | null {
    return value.trim() ? value.trim() : null
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const editable: PortfolioEditableInput = {
      snapshot_date: snapshotDate,
      units: holdingUnits,
      market_value: marketValue,
      holding_profit: holdingProfit,
      holding_return_pct: holdingReturn,
      cumulative_profit: optionalNumber(cumulativeProfit),
      recurring_plan: recurringEnabled
        ? {
          gross_amount: recurringGross,
          fee_pct: recurringFee || '0',
          confirmation_lag_days: Number(recurringLag),
        }
        : null,
      purchase_fee_pct: optionalNumber(purchaseFee),
      management_fee_pct_annual: optionalNumber(managementFee),
      custody_fee_pct_annual: optionalNumber(custodyFee),
    }
    mutation.mutate(target.kind === 'create'
      ? { ...editable, share_code: shareCode.trim(), platform: platform.trim() }
      : editable)
  }

  return (
    <div className="portfolio-dialog-backdrop" role="presentation">
      <section
        className="portfolio-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="portfolio-dialog-title"
      >
        <div className="portfolio-dialog-heading">
          <div>
            <span className="section-kicker">USER REPORTED SNAPSHOT</span>
            <h2 id="portfolio-dialog-title">
              {target.kind === 'create' ? '手动加入持仓' : '修正持仓快照'}
            </h2>
            <p>
              以平台同日快照为基线，后续按真实持有份额与净值变化更新市值和日收益。
            </p>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭">
            <X size={18} />
          </button>
        </div>

        <form className="portfolio-dialog-form" onSubmit={submit}>
          {target.kind === 'create' ? (
            <div className="portfolio-form-grid">
              <label>基金代码<input required pattern="[0-9]{6}" value={shareCode} onChange={(event) => setShareCode(event.target.value)} placeholder="六位基金代码" /></label>
              <label>平台<input required maxLength={100} value={platform} onChange={(event) => setPlatform(event.target.value)} placeholder="例如：示例平台" /></label>
            </div>
          ) : (
            <div className="portfolio-readonly-identity">
              <strong>{position?.canonical_name}</strong>
              <span><code>{position?.share_code}</code>{position?.platform} · {position?.currency}</span>
            </div>
          )}

          <fieldset>
            <legend>持仓快照</legend>
            <p>持有份额是后续估值主数据；市值、收益和收益率共同保存为同日平台快照基线。</p>
            <div className="portfolio-form-grid portfolio-form-grid-three">
              <label>快照日期<input required type="date" value={snapshotDate} onChange={(event) => setSnapshotDate(event.target.value)} /></label>
              <label>持有份额（主数据）<input required type="number" min="0.00000001" step="0.00000001" value={holdingUnits} onChange={(event) => setHoldingUnits(event.target.value)} /></label>
              <label>平台快照市值（参考）<input required type="number" min="0.01" step="0.01" value={marketValue} onChange={(event) => setMarketValue(event.target.value)} /></label>
              <label>快照持有收益<input required type="number" step="0.01" value={holdingProfit} onChange={(event) => setHoldingProfit(event.target.value)} /></label>
              <label>快照持有收益率（%）<input required type="number" step="0.0001" value={holdingReturn} onChange={(event) => setHoldingReturn(event.target.value)} /></label>
              <label>累计收益（可空）<input type="number" step="0.01" value={cumulativeProfit} onChange={(event) => setCumulativeProfit(event.target.value)} /></label>
            </div>
            {position && (
              <p className="portfolio-form-warning">修改份额或快照锚点会用新快照替代旧基线，并清除该快照之后生成的定投订单与确认流水，避免重复计算份额。</p>
            )}
          </fieldset>

          <fieldset>
            <legend>每日定投</legend>
            <label className="portfolio-checkbox"><input type="checkbox" checked={recurringEnabled} onChange={(event) => setRecurringEnabled(event.target.checked)} />启用每日定投计划</label>
            {recurringEnabled && (
              <div className="portfolio-form-grid">
                <label>每日扣款金额<input required type="number" min="0.01" step="0.01" value={recurringGross} onChange={(event) => setRecurringGross(event.target.value)} /></label>
                <label>平台费率（%）<input required type="number" min="0" max="100" step="0.0001" value={recurringFee} onChange={(event) => setRecurringFee(event.target.value)} /></label>
                <label>预计确认周期（T+）<input required type="number" min="0" max="10" step="1" value={recurringLag} onChange={(event) => setRecurringLag(event.target.value)} /></label>
              </div>
            )}
          </fieldset>

          <fieldset>
            <legend>手工费率修正（可空）</legend>
            <p>留空时继续使用公开来源；填写后明确作为本地手工口径。</p>
            <div className="portfolio-form-grid portfolio-form-grid-three">
              <label>申购费率（%）<input type="number" min="0" max="100" step="0.0001" value={purchaseFee} onChange={(event) => setPurchaseFee(event.target.value)} /></label>
              <label>管理费率（年，%）<input type="number" min="0" max="100" step="0.0001" value={managementFee} onChange={(event) => setManagementFee(event.target.value)} /></label>
              <label>托管费率（年，%）<input type="number" min="0" max="100" step="0.0001" value={custodyFee} onChange={(event) => setCustodyFee(event.target.value)} /></label>
            </div>
          </fieldset>

          {mutation.isError && <ErrorPanel compact error={mutation.error} />}
          <div className="portfolio-dialog-actions">
            <button className="button button-secondary" type="button" onClick={onClose}>取消</button>
            <button className="button button-primary" type="submit" disabled={mutation.isPending}>
              {mutation.isPending ? '正在保存…' : target.kind === 'create' ? '确认加入' : '保存并重新计算'}
            </button>
          </div>
        </form>
      </section>
    </div>
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
  const queryClient = useQueryClient()
  const refreshedOperationRef = useRef<string | number | null>(null)
  const [sort, setSort] = useState<{ key: SortKey | null; direction: SortDirection }>({
    key: null,
    direction: 'desc',
  })
  const [dialogTarget, setDialogTarget] = useState<PositionDialogTarget | null>(null)
  const [consistencyRequested, setConsistencyRequested] = useState(false)
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
  const preparationQuery = useQuery({
    queryKey: ['data-preparation-status'],
    queryFn: ({ signal }) => api.dataPreparationStatus(signal),
    enabled: portfolioEnabled,
    refetchInterval: (query) => {
      const status = query.state.data?.latest_operation?.status
      return status === 'queued' || status === 'running' ? 2_000 : false
    },
  })
  const refreshMutation = useMutation({
    mutationFn: (fundCodes: string[]) => api.runDataOperation('sync-daily', fundCodes),
    onSuccess: async () => {
      await preparationQuery.refetch()
    },
  })
  const portfolio = portfolioQuery.data
  const positions = useMemo(() => portfolio?.positions ?? [], [portfolio])
  const consistencyQuery = useQuery({
    queryKey: ['portfolio', 'consistency'],
    queryFn: ({ signal }) => api.portfolioConsistency(signal),
    enabled: portfolioEnabled && positions.length > 0 && consistencyRequested,
    staleTime: 5 * 60 * 1000,
  })
  const cny = summaryFor(portfolio?.currency_summaries ?? [], 'CNY')
  const usd = summaryFor(portfolio?.currency_summaries ?? [], 'USD')
  const recurringCount = positions.filter((position) => position.recurring_plan).length
  const currentRepresentativeCodes = useMemo(
    () => [...new Set(positions.map((position) => position.representative_code))].sort(),
    [positions],
  )
  const todayInShanghai = shanghaiDate(new Date().toISOString())
  const shanghaiWeekday = todayInShanghai
    ? new Date(`${todayInShanghai}T00:00:00Z`).getUTCDay()
    : null
  const recurringOrdersTriggeredToday = recurringCount === 0
    || shanghaiWeekday === 0
    || shanghaiWeekday === 6
    || positions
      .filter((position) => position.recurring_plan)
      .every((position) => position.latest_recurring_order?.order_date === todayInShanghai)
  const persistedOperation = preparationQuery.data?.latest_operation
  const latestDailyOperation = preparationQuery.data?.latest_daily_operation
  const submittedOperation = refreshMutation.data
  const refreshOperation = submittedOperation && persistedOperation?.id === submittedOperation.id
    ? persistedOperation
    : submittedOperation
  const globalOperationActive = persistedOperation?.status === 'queued'
    || persistedOperation?.status === 'running'
  const refreshOperationActive = refreshOperation?.status === 'queued'
    || refreshOperation?.status === 'running'
  const anotherOperationActive = globalOperationActive && !refreshOperationActive
  const todayRefreshDone = (latestDailyOperation?.status === 'succeeded'
      || latestDailyOperation?.status === 'partial')
    && shanghaiDate(latestDailyOperation.finished_at) === todayInShanghai
    && currentRepresentativeCodes.every((code) => latestDailyOperation.fund_codes.includes(code))
    && recurringOrdersTriggeredToday
  const refreshBusy = preparationQuery.isPending || refreshMutation.isPending
    || globalOperationActive || refreshOperationActive
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

  useEffect(() => {
    if (!refreshOperation || refreshOperationActive) return
    if (refreshedOperationRef.current === refreshOperation.id) return
    refreshedOperationRef.current = refreshOperation.id
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ['portfolio'] }),
      queryClient.invalidateQueries({ queryKey: ['funds'] }),
      queryClient.invalidateQueries({ queryKey: ['data-preparation-status'] }),
    ])
  }, [queryClient, refreshOperation, refreshOperationActive])

  function toggleSort(key: SortKey) {
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === 'desc' ? 'asc' : 'desc',
    }))
  }

  async function positionSaved() {
    setDialogTarget(null)
    setConsistencyRequested(false)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['portfolio'] }),
      queryClient.invalidateQueries({ queryKey: ['funds'] }),
      queryClient.invalidateQueries({ queryKey: ['data-preparation-status'] }),
    ])
  }

  return (
    <div className="page-stack">
      <section className="page-intro portfolio-intro">
        <div className="detail-title">
          <span className="code-chip"><WalletCards size={30} /></span>
          <div>
            <span className="eyebrow">LOCAL PORTFOLIO · 用户快照</span>
            <h1>我的持仓</h1>
            <p>以平台同日快照为基线，后续按真实持有份额与已归档净值变化更新参考市值。</p>
          </div>
        </div>
        <div className="as-of-card">
          <RefreshCw size={18} />
          <span>最新净值日</span>
          <strong>{formatDate(portfolio?.latest_nav_date)}</strong>
          <button
            className="portfolio-data-refresh"
            type="button"
            disabled={positions.length === 0 || refreshBusy || todayRefreshDone}
            onClick={() => refreshMutation.mutate([...new Set(positions.map((position) => position.share_code))])}
          >
            <RefreshCw size={13} className={refreshBusy ? 'spin' : ''} />
            {preparationQuery.isPending
              ? '正在检查任务…'
              : anotherOperationActive
                ? '其他数据任务运行中'
                : refreshMutation.isPending || refreshOperationActive
              ? '正在刷新…'
              : todayRefreshDone
                ? '今日已刷新'
              : recurringCount > 0
                ? `刷新并触发今日定投（${recurringCount} 个）`
                : '刷新持仓数据'}
          </button>
          <small>
            {todayRefreshDone
              ? `今天已完成刷新并触发计划；最新净值日 ${formatDate(portfolio?.latest_nav_date)}，同一持仓不会重复下单。`
              : recurringCount > 0
              ? `同步近 10 天数据并触发今日计划；订单先等待申购日净值，确认后才计入本金和份额。`
              : '同步近 10 天净值、价格、限额与汇率；完成后自动刷新本页。'}
          </small>
          {refreshOperation && !refreshOperationActive && (
            <small className={`portfolio-refresh-result tone-${refreshOperation.status}`} role="status">
              任务 #{refreshOperation.id}：{statusLabel(refreshOperation.status)} · 今日下单 {refreshOperation.recurring_orders_created ?? 0} 笔 · 确认 {refreshOperation.recurring_orders_settled ?? 0} 笔 · 数据写入 {refreshOperation.records_written} · 失败 {refreshOperation.records_failed}
            </small>
          )}
          {refreshMutation.isError && (
            <small className="portfolio-refresh-error" role="alert">
              {refreshMutation.error instanceof Error ? refreshMutation.error.message : '刷新任务提交失败'}
            </small>
          )}
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
        <>
          <EmptyPanel title="尚未导入本地持仓" detail="可以下载模板批量导入，也可以使用下方按钮手动加入一只持仓。" />
          <div className="portfolio-empty-action">
            <button className="button button-primary" type="button" onClick={() => setDialogTarget({ kind: 'create' })}>
              <Plus size={15} />手动加入持仓
            </button>
          </div>
        </>
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
              <small>{recurringCount} 个计划 · 当日净投入 {money(cny?.recurring_net_amount, 'CNY')} · 到账 {formatPercent(cny?.recurring_net_pct, 2)}</small>
              <small>等待确认 {cny?.recurring_pending_order_count ?? 0} 笔 · {money(cny?.recurring_pending_gross_amount, 'CNY')} 尚未计入本金</small>
              <small>累计结算 {cny?.recurring_execution_count ?? 0} 笔 · 扣款 {money(cny?.recurring_invested_gross_amount, 'CNY')} · 买入 {money(cny?.recurring_invested_net_amount, 'CNY')}</small>
            </article>
          </section>

          <PortfolioConsistencyPanel
            analysis={consistencyQuery.data}
            requested={consistencyRequested}
            pending={consistencyQuery.isPending && consistencyRequested}
            error={consistencyQuery.error}
            onRun={() => {
              if (consistencyRequested) void consistencyQuery.refetch()
              else setConsistencyRequested(true)
            }}
          />

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
                    <th className="numeric">持有份额</th>
                    <SortableHeader columnKey="estimated_market_value_cny" label="参考市值" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />
                    <SortableHeader columnKey="latest_daily_return_pct" label="最新涨跌" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />
                    <SortableHeader columnKey="estimated_daily_profit_amount_cny" label="最新日收益" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />
                    <SortableHeader columnKey="estimated_profit_amount_cny" label="持有收益" activeKey={sort.key} direction={sort.direction} onSort={toggleSort} />
                    <th className="numeric">累计收益 / 分红</th>
                    <th>每日定投</th>
                    <th>平台手续费</th>
                    <th>年运作费率</th>
                    <th>操作</th>
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
                        <strong>{units(position.estimated_units)}</strong>
                        <small className="table-subline">快照 {units(position.reported_units)}</small>
                      </td>
                      <td className="numeric metric-cell">
                        {money(position.estimated_market_value, position.currency)}
                        <small className="table-subline">快照 {money(position.reported_market_value, position.currency)}</small>
                        {position.currency === 'USD' && <small className="table-subline">折合 {money(position.estimated_market_value_cny, 'CNY')}</small>}
                      </td>
                      <td className={`numeric metric-cell ${returnTone(position.latest_daily_return_pct)}`}>
                        {signedPercent(position.latest_daily_return_pct)}
                        <small className="table-subline">净值日 {formatDate(position.latest_nav_date)}</small>
                      </td>
                      <td className={`numeric metric-cell ${returnTone(position.estimated_daily_profit_amount)}`}>
                        {signedMoney(position.estimated_daily_profit_amount, position.currency)}
                        <small className="table-subline">净值日 {formatDate(position.latest_nav_date)}</small>
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
                            <strong>每日 {money(position.recurring_plan.gross_amount, position.currency)}</strong>
                            <small>净买入 {money(position.recurring_plan.net_amount, position.currency)} · 预计 T+{position.recurring_plan.confirmation_lag_days}</small>
                            {position.latest_recurring_order?.status === 'PENDING' ? (
                              <small className="portfolio-order-status is-pending">
                                {formatDate(position.latest_recurring_order.order_date)} 已触发 · 等待确认至约 {formatDate(position.latest_recurring_order.expected_confirmation_date)}
                              </small>
                            ) : position.latest_recurring_order?.status === 'SETTLED' ? (
                              <small className="portfolio-order-status is-settled">
                                {formatDate(position.latest_recurring_order.order_date)} 已确认 · 净值日 {formatDate(position.latest_recurring_order.settled_nav_date)}
                              </small>
                            ) : (
                              <small className="portfolio-order-status">今日尚未触发</small>
                            )}
                            <small>已结算 {position.recurring_execution_count ?? 0} 笔 · 累计 {money(position.recurring_invested_gross_amount, position.currency)}</small>
                            <small>最近净值日 {formatDate(position.last_recurring_nav_date)}</small>
                          </span>
                        ) : '—'}
                      </td>
                      <td>
                        <span className="portfolio-fee">
                          <strong>{feeLabel(position)}</strong>
                          <small>{position.fees.platform_purchase_fee_pct === null ? '可在修正浮窗补充' : '用户提供的平台口径'}</small>
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
                      <td>
                        <button
                          className="button button-secondary portfolio-edit-button"
                          type="button"
                          onClick={() => setDialogTarget({ kind: 'edit', position })}
                        >
                          <Pencil size={13} />修正
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="panel-note"><ReceiptText size={13} /> 参考市值以平台快照为基线，后续涨跌和日收益按真实份额与最新净值计算；平台收益和收益率保留成本口径。最新涨幅、净值、汇率和一致性结果不能手工修改。</p>
            <div className="portfolio-add-action">
              <button className="button button-primary" type="button" onClick={() => setDialogTarget({ kind: 'create' })}>
                <Plus size={15} />手动加入持仓
              </button>
              <small>适合单只录入；多只持仓仍建议使用上方 XLSX 模板。</small>
            </div>
          </section>
        </>
      )}
      {dialogTarget && (
        <PortfolioPositionDialog
          key={dialogTarget.kind === 'edit' ? String(dialogTarget.position.id) : 'create'}
          target={dialogTarget}
          onClose={() => setDialogTarget(null)}
          onSaved={() => { void positionSaved() }}
        />
      )}
    </div>
  )
}

function reportPeriodLabel(analysis: PortfolioConsistencyPayload | undefined): string {
  const value = analysis?.funds[0]?.report_period_end
  if (!value) return '最近报告期'
  const parsed = new Date(`${value}T00:00:00`)
  if (Number.isNaN(parsed.getTime())) return '最近报告期'
  return `${parsed.getFullYear()} Q${Math.floor(parsed.getMonth() / 3) + 1}`
}

function PortfolioConsistencyPanel({
  analysis,
  requested,
  pending,
  error,
  onRun,
}: {
  analysis: PortfolioConsistencyPayload | undefined
  requested: boolean
  pending: boolean
  error: unknown
  onRun: () => void
}) {
  const prediction = analysis?.portfolio_prediction
  const periodLabel = reportPeriodLabel(analysis)

  return (
    <section className="panel q2-panel portfolio-q2-panel" aria-labelledby="portfolio-consistency-title">
      <div className="panel-heading q2-panel-heading">
        <div>
          <span className="section-kicker">PORTFOLIO CONSISTENCY</span>
          <h2 id="portfolio-consistency-title">持仓一致性</h2>
          <p>按需汇总当前持仓中的主动基金；季度静态披露用于解释偏差，不代表当前真实组合。</p>
        </div>
        <button className="button button-primary" type="button" onClick={onRun} disabled={pending}>
          <RefreshCw size={15} className={pending ? 'spin' : ''} />
          {pending ? '正在分析…' : analysis ? '重新运行分析' : '运行持仓一致性分析'}
        </button>
      </div>

      {!requested && !analysis && (
        <div className="portfolio-consistency-idle">
          <strong>分析不会随页面加载自动运行</strong>
          <span>点击后只分析当前持仓内符合条件的主动基金，避免日常浏览触发较重的行情计算。</span>
        </div>
      )}
      {pending && <LoadingPanel label="正在计算当前持仓的报告期解释力与偏差…" />}
      {requested && Boolean(error) && <ErrorPanel compact error={error} onRetry={onRun} />}

      {analysis && !pending && !error && (
        <>
          <div className="q2-portfolio-metrics" aria-label="组合一致性摘要">
            <article>
              <span>组合最新估算涨跌</span>
              <strong className={returnTone(prediction?.predicted_return_pct)}>{signedPercent(prediction?.predicted_return_pct)}</strong>
              <small>区间 {signedPercent(prediction?.lower_bound_pct)} ～ {signedPercent(prediction?.upper_bound_pct)}</small>
            </article>
            <article>
              <span>已分析组合权重</span>
              <strong>{formatPercent(prediction?.analyzed_portfolio_weight_pct)}</strong>
              <small>缺失估计不按 0，也不重归一化</small>
            </article>
            <article>
              <span>主动基金</span>
              <strong>{analysis.funds.length}</strong>
              <small>按基金合同聚合重复份额</small>
            </article>
            <article>
              <span>报告期 / 数据截至</span>
              <strong className="q2-date-value">{periodLabel}</strong>
              <small>{formatDate(analysis.data_as_of)}</small>
            </article>
          </div>

          {analysis.funds.length > 0 ? (
            <div className="data-table-wrap q2-table-wrap">
              <table className="data-table q2-fund-table">
                <thead>
                  <tr>
                    <th>主动基金 / 份额</th>
                    <th>状态 / 最近偏差</th>
                    <th className="numeric">组合权重</th>
                    <th className="numeric">最新估算涨跌</th>
                    <th className="numeric">最近已披露实际</th>
                    <th className="numeric">实际 − 估算</th>
                    <th className="numeric">分析期累计</th>
                    <th className="numeric">解释覆盖</th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.funds.map((fund) => {
                    const hasActual = toNumber(fund.actual_return_pct) !== null
                    const hasDifference = hasActual && toNumber(fund.actual_minus_predicted_pct) !== null
                    const hasCumulative = toNumber(fund.quarter_cumulative_actual_minus_predicted_pct) !== null
                    return (
                      <tr key={String(fund.fund_id)}>
                        <td className="fund-column">
                          <Link className="fund-identity" to={`/funds/${fund.fund_id}`}>
                            <strong>{fund.fund_name}</strong>
                            <span><code>{fund.representative_code}</code>{fund.share_codes.join(' / ')}</span>
                          </Link>
                          <small className="table-subline">报告期 {formatDate(fund.report_period_end)}</small>
                        </td>
                        <td>
                          <StatusBadge value={fund.status} />
                          <small className="table-subline">最近验证 {hasDifference ? signedPercentagePoints(fund.actual_minus_predicted_pct) : '待公布'}</small>
                        </td>
                        <td className="numeric">{formatPercent(fund.portfolio_weight_pct)}</td>
                        <td className={`numeric ${returnTone(fund.predicted_return_pct)}`}>
                          {signedPercent(fund.predicted_return_pct)}
                          <small className="table-subline">收益日 {formatDate(fund.prediction_date)} · 净值日 {formatDate(fund.prediction_nav_date)}</small>
                        </td>
                        <td className={`numeric ${hasActual ? returnTone(fund.actual_return_pct) : ''}`}>
                          {hasActual ? signedPercent(fund.actual_return_pct) : <span className="q2-pending-value">待公布</span>}
                          <small className="table-subline">{hasActual ? `收益日 ${formatDate(fund.comparison_date)} · 净值日 ${formatDate(fund.comparison_nav_date)}` : '等待已披露净值'}</small>
                        </td>
                        <td className={`numeric ${hasDifference ? returnTone(fund.actual_minus_predicted_pct) : ''}`}>
                          {hasDifference ? signedPercentagePoints(fund.actual_minus_predicted_pct) : <span className="q2-pending-value">待公布</span>}
                          <small className="table-subline">{hasDifference ? `${fund.comparison_analysis_mode ?? '模式未知'} · 同期估算 ${signedPercent(fund.comparison_predicted_return_pct)}` : '等待同一收益日实际'}</small>
                        </td>
                        <td className={`numeric q2-cumulative-cell ${hasCumulative ? returnTone(fund.quarter_cumulative_actual_minus_predicted_pct) : ''}`}>
                          {hasCumulative ? `偏差 ${signedPercentagePoints(fund.quarter_cumulative_actual_minus_predicted_pct)}` : <span className="q2-pending-value">数据不足</span>}
                          <small className="table-subline">{hasCumulative ? `实际 ${signedPercent(fund.quarter_cumulative_actual_return_pct)} · 估算 ${signedPercent(fund.quarter_cumulative_predicted_return_pct)}` : '可比较序列不完整'}</small>
                          {hasCumulative && <small className="table-subline">截至 {formatDate(fund.quarter_cumulative_through_date)} · {fund.quarter_cumulative_observation_count} 个交易日</small>}
                        </td>
                        <td className="numeric">{formatPercent(fund.coverage_pct)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <p className="q2-comparison-note">“实际 − 估算”只比较同一个收益日。累计实际与累计估算均从分析起点按可比较交易日逐日复利；累计偏差是两条累计收益之差，不是每日误差简单相加。该结果用于观察静态报告持仓的解释力是否漂移，不能据此断言基金经理买卖了某只证券。</p>
            </div>
          ) : (
            <EmptyPanel compact title="没有可分析的主动基金" detail="ETF、指数基金和 ETF 联接不运行主动持仓偏离模型。" />
          )}

          <div className="q2-portfolio-detail-grid">
            <div className="q2-info-card">
              <h3>{periodLabel} 静态暴露</h3>
              <div className="q2-exposure-columns">
                <div>
                  <strong>国家 / 地区</strong>
                  <div className="q2-exposure-list">
                    {analysis.country_exposure.slice(0, 8).map((item) => <span key={item.name}>{item.name}<b>{formatPercent(item.portfolio_exposure_pct)}</b></span>)}
                    {analysis.country_exposure.length === 0 && <small>暂无可靠国家暴露</small>}
                  </div>
                </div>
                <div>
                  <strong>行业</strong>
                  <div className="q2-exposure-list">
                    {analysis.industry_exposure.slice(0, 8).map((item) => <span key={item.name}>{item.name}<b>{formatPercent(item.portfolio_exposure_pct)}</b></span>)}
                    {analysis.industry_exposure.length === 0 && <small>暂无可靠行业暴露</small>}
                  </div>
                </div>
              </div>
            </div>

            <div className="q2-info-card">
              <h3><Layers3 size={15} />基金底层重叠</h3>
              <div className="q2-overlap-list">
                {analysis.overlaps.slice(0, 5).map((overlap) => (
                  <article key={`${overlap.left_fund_id}-${overlap.right_fund_id}`}>
                    <strong>{overlap.left_fund_name} × {overlap.right_fund_name}</strong>
                    <span>{periodLabel} 披露重叠 {formatPercent(overlap.overlap_weight_pct)}</span>
                    <small>{overlap.securities.slice(0, 4).map((item) => item.security_name).join('、')}</small>
                  </article>
                ))}
                {analysis.overlaps.length === 0 && <p className="q2-empty-copy">当前披露证券中没有可展示的基金两两重叠。</p>}
              </div>
            </div>
          </div>

          <dl className="q2-date-list q2-portfolio-dates">
            <div><dt>分析起点</dt><dd>{formatDate(analysis.analysis_start_date)}</dd></div>
            <div><dt>分析 as_of</dt><dd>{formatDate(analysis.as_of)}</dd></div>
            <div><dt>行情获取</dt><dd>{formatDate(analysis.market_data_fetched_at, true)}</dd></div>
          </dl>
          <ul className="q2-limitations" aria-label="持仓一致性分析限制">
            {analysis.limitations.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </>
      )}
    </section>
  )
}
