import { issueTone, statusLabel } from '../lib/format'

export function StatusBadge({ value, label }: { value: unknown; label?: string }) {
  const tone = issueTone(value)
  return <span className={`status-badge status-${tone}`}><i />{label ?? statusLabel(value)}</span>
}
