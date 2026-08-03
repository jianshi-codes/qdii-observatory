import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api/client'
import type { FundSummary } from '../api/types'
import { formatDate, toNumber } from '../lib/format'

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

function returnTone(value: unknown): string {
  const number = toNumber(value)
  if (number === null || number === 0) return ''
  return number > 0 ? 'return-positive' : 'return-negative'
}

export function OnDemandEstimateCell({ fund }: { fund: FundSummary }) {
  const [requested, setRequested] = useState(false)
  const id = String(fund.id ?? fund.representative_code)
  const estimateQuery = useQuery({
    queryKey: ['fund', id, 'today-estimate', fund.representative_code],
    queryFn: ({ signal }) => api.fundTodayEstimate(
      id,
      { shareCode: fund.representative_code },
      signal,
    ),
    enabled: requested,
    retry: false,
  })

  if (!requested) {
    return (
      <div className="q2-on-demand-cell">
        <button
          className="button button-quiet q2-estimate-button"
          type="button"
          aria-label={`加载 ${fund.canonical_name} 代表份额 ${fund.representative_code} 的 Q2 估算`}
          onClick={() => setRequested(true)}
        >
          加载代表份额估算
        </button>
        <small>代表份额 {fund.representative_code} · 点击后才请求</small>
      </div>
    )
  }

  if (estimateQuery.isPending || estimateQuery.isFetching) {
    return (
      <div className="q2-on-demand-cell" aria-live="polite">
        <span className="q2-estimate-state">正在计算…</span>
        <small>代表份额 {fund.representative_code}</small>
      </div>
    )
  }

  if (estimateQuery.isError) {
    return (
      <div className="q2-on-demand-cell" role="alert">
        <span className="q2-estimate-error">估算暂时不可用</span>
        <button
          className="button button-quiet q2-estimate-button"
          type="button"
          aria-label={`重试 ${fund.canonical_name} 的 Q2 估算`}
          onClick={() => void estimateQuery.refetch()}
        >
          <RefreshCw size={12} />重试
        </button>
      </div>
    )
  }

  const analysis = estimateQuery.data
  if (analysis.consistency.status === 'NOT_APPLICABLE') {
    return (
      <div className="q2-on-demand-cell" aria-live="polite">
        <strong>不适用</strong>
        <small>该代表份额不运行主动基金 Q2 基线</small>
      </div>
    )
  }

  const prediction = analysis.prediction
  const comparison = analysis.latest_comparison
  return (
    <div className="q2-on-demand-cell" aria-live="polite">
      <dl className="q2-on-demand-values">
        <div>
          <dt>最新估算</dt>
          <dd className={returnTone(prediction?.predicted_return_pct)}>
            {toNumber(prediction?.predicted_return_pct) === null
              ? '数据不足'
              : signedPercent(prediction?.predicted_return_pct)}
          </dd>
          <small>{prediction
            ? `收益日 ${formatDate(prediction.estimate_date)} · 对应净值日 ${formatDate(prediction.nav_date)}`
            : '等待可用行情'}</small>
        </div>
        <div>
          <dt>最近已披露实际</dt>
          <dd className={returnTone(comparison?.actual_return_pct)}>
            {comparison ? signedPercent(comparison.actual_return_pct) : '待公布'}
          </dd>
          <small>{comparison
            ? `收益日 ${formatDate(comparison.comparison_date)} · 净值日 ${formatDate(comparison.nav_date)}`
            : '尚无已披露实际'}</small>
        </div>
        <div>
          <dt>实际 − 估算</dt>
          <dd className={returnTone(comparison?.actual_minus_predicted_pct)}>
            {comparison
              ? signedPercentagePoints(comparison.actual_minus_predicted_pct)
              : '待公布'}
          </dd>
          <small>{comparison
            ? `收益日 ${formatDate(comparison.comparison_date)} · 同期估算 ${signedPercent(comparison.predicted_return_pct)}`
            : '等待同一收益日实际'}</small>
        </div>
      </dl>
      <small className="q2-on-demand-scope">代表份额 {analysis.share_code}</small>
    </div>
  )
}
