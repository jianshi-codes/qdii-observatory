import { AlertTriangle, Inbox, RefreshCw, WifiOff } from 'lucide-react'
import type { ReactNode } from 'react'

export function LoadingPanel({ label = '正在读取本地数据…' }: { label?: string }) {
  return (
    <div className="state-panel" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <strong>{label}</strong>
      <span>大型归档首次查询可能需要一点时间</span>
    </div>
  )
}

export function ErrorPanel({
  error,
  onRetry,
  compact = false,
}: {
  error: unknown
  onRetry?: () => void
  compact?: boolean
}) {
  const message = error instanceof Error ? error.message : '请求发生未知错误。'
  return (
    <div className={compact ? 'state-panel state-panel-compact state-error' : 'state-panel state-error'} role="alert">
      <WifiOff size={compact ? 22 : 28} />
      <strong>这部分数据暂时不可用</strong>
      <span>{message}</span>
      {onRetry && (
        <button className="button button-secondary" type="button" onClick={onRetry}>
          <RefreshCw size={15} />重新请求
        </button>
      )}
    </div>
  )
}

export function EmptyPanel({
  title = '暂无可展示数据',
  detail = '来源尚未归档或解析结果为空。',
  compact = false,
  icon = 'empty',
  action,
}: {
  title?: string
  detail?: string
  compact?: boolean
  icon?: 'empty' | 'warning'
  action?: ReactNode
}) {
  return (
    <div className={compact ? 'state-panel state-panel-compact' : 'state-panel'}>
      {icon === 'warning' ? <AlertTriangle size={compact ? 22 : 28} /> : <Inbox size={compact ? 22 : 28} />}
      <strong>{title}</strong>
      <span>{detail}</span>
      {action}
    </div>
  )
}
