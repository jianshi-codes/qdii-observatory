import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

export function MetricCard({
  label,
  value,
  detail,
  icon: Icon,
  tone = 'ink',
  children,
}: {
  label: string
  value: string
  detail?: string
  icon?: LucideIcon
  tone?: 'ink' | 'coral' | 'jade' | 'gold'
  children?: ReactNode
}) {
  return (
    <article className={`metric-card metric-${tone}`}>
      <div className="metric-card-top">
        <span>{label}</span>
        {Icon && <Icon size={17} />}
      </div>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
      {children}
    </article>
  )
}
