export function toNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value.replace('%', '').replaceAll(',', ''))
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

export function formatPercent(value: unknown, digits = 1): string {
  const number = toNumber(value)
  return number === null ? '—' : `${number.toFixed(digits)}%`
}

export function formatConfidence(value: unknown, digits = 1): string {
  const number = toNumber(value)
  if (number === null) return '—'
  const percent = Math.abs(number) <= 1 ? number * 100 : number
  return `${percent.toFixed(digits)}%`
}

export function formatNumber(value: unknown, digits = 2): string {
  const number = toNumber(value)
  return number === null
    ? '—'
    : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: digits }).format(number)
}

export function formatMoney(value: unknown): string {
  const number = toNumber(value)
  if (number === null) return '—'
  return new Intl.NumberFormat('zh-CN', {
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(number)
}

export function formatDate(value: unknown, includeTime = false): string {
  if (typeof value !== 'string' || !value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    ...(includeTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  }).format(date)
}

export function displayText(value: unknown, fallback = '未提供'): string {
  if (typeof value === 'string' && value.trim()) return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (typeof value === 'boolean') return value ? '是' : '否'
  return fallback
}

export function field(source: Record<string, unknown>, ...keys: string[]): unknown {
  for (const key of keys) {
    if (source[key] !== null && source[key] !== undefined) return source[key]
  }
  const metrics = source.metrics
  if (metrics && typeof metrics === 'object') {
    for (const key of keys) {
      const value = (metrics as Record<string, unknown>)[key]
      if (value !== null && value !== undefined) return value
    }
  }
  return undefined
}

export const techScopeLabels: Record<string, string> = {
  GLOBAL_SEMICONDUCTOR: '全球半导体',
  CHINA_KOREA_SEMICONDUCTOR: '中韩半导体',
  NASDAQ_TECH_PURE: '纯纳指科技',
  NASDAQ_100_MEGA_CAP_GROWTH: '纳指 100 大盘成长',
  GLOBAL_ACTIVE_TECH_HIGH: '全球主动 · 高科技暴露',
  GLOBAL_ACTIVE_TECH_MIXED: '全球主动 · 科技混合',
  GLOBAL_ACTIVE_BROAD: '全球主动 · 宽基',
  GLOBAL_TECHNOLOGY_INTERNET: '全球科技 / 互联网',
  UNKNOWN: '待识别',
}

export function techScopeLabel(value: unknown): string {
  if (typeof value !== 'string' || !value) return '待识别'
  return techScopeLabels[value] ?? value.replaceAll('_', ' ')
}

export const researchScopeLabels: Record<string, string> = {
  TECHNOLOGY: '科技相关',
  EQUITY: '权益',
  FIXED_INCOME: '固收',
  COMMODITY: '商品',
  REAL_ESTATE: '房地产 / REITs',
  OTHER: '其他',
}

export function researchScopeLabel(value: unknown): string {
  if (typeof value !== 'string' || !value) return '其他'
  return researchScopeLabels[value] ?? value.replaceAll('_', ' ')
}

export function wrapperLabel(value: unknown): string {
  if (typeof value !== 'string' || !value) return 'wrapper 待识别'
  const labels: Record<string, string> = {
    DIRECT: '直接持股',
    ETF_FEEDER: 'ETF 联接',
    ETF: 'ETF',
    LOF: 'LOF',
    FUND_OF_FUNDS: '基金中基金',
    FOF: '基金中基金',
    DIRECT_EQUITY: '直接持股',
    ACTIVE_EQUITY: '主动权益',
  }
  return labels[value] ?? value.replaceAll('_', ' ')
}

export function relationTypeLabel(value: unknown): string {
  const labels: Record<string, string> = {
    SAME_CONTRACT_SHARE: '同合同份额',
    FEEDER_TO_TARGET_ETF: '联接至目标 ETF',
    SAME_INDEX_FAMILY: '同指数族',
    REPORT_FUND_HOLDING: '报告披露基金持仓',
  }
  return typeof value === 'string' ? labels[value] ?? value.replaceAll('_', ' ') : '关系未标注'
}

export function reportTypeLabel(value: unknown): string {
  const labels: Record<string, string> = {
    QUARTERLY: '季度报告',
    ANNUAL: '年度报告',
    SEMIANNUAL: '中期报告',
  }
  return typeof value === 'string' ? labels[value] ?? value : '基金报告'
}

export function issueTone(value: unknown): 'good' | 'warn' | 'bad' | 'neutral' {
  const normalized = String(value ?? '').toLowerCase()
  if (['success', 'succeeded', 'healthy', 'parsed', 'valid_empty', 'completed', 'resolved', 'direct_only', 'closed', 'consistent', 'ready'].includes(normalized)) {
    return 'good'
  }
  if (['warning', 'low_confidence', 'degraded', 'rate_limited', 'partial', 'queued', 'running', 'pending', 'unresolved', 'open', 'slightly_diverging', 'insufficient_data', 'stale', 'missing_nav', 'missing_baseline', 'missing_report', 'report_not_parsed', 'missing_exposure'].includes(normalized)) {
    return 'warn'
  }
  if (['error', 'failed', 'failed_with_reason', 'schema_changed', 'circular_relation_detected', 'critical', 'high', 'likely_exposure_changed'].includes(normalized)) {
    return 'bad'
  }
  return 'neutral'
}

export function providerHealthLabel(value: unknown): string {
  const normalized = String(value ?? '').toLowerCase()
  const labels: Record<string, string> = {
    healthy: '健康',
    degraded: '降级',
    rate_limited: '受到限流',
    schema_changed: '来源结构变化',
    disabled: '已停用',
    unknown: '尚未验证',
  }
  return labels[normalized] ?? (value ? String(value) : '尚未验证')
}

export function lookthroughStatusLabel(value: unknown): string {
  const normalized = String(value ?? '').toLowerCase()
  const labels: Record<string, string> = {
    resolved: '已完成穿透',
    direct_only: '仅直接持仓',
    partial: '部分穿透',
    unresolved: '待解决穿透',
    not_calculated: '尚未计算',
    not_available: '不可用',
    circular_relation_detected: '检测到循环关系',
  }
  return labels[normalized] ?? (value ? String(value) : '状态未知')
}

export function statusLabel(value: unknown): string {
  const normalized = String(value ?? '').toLowerCase()
  const labels: Record<string, string> = {
    parsed: '已解析',
    valid_empty: '有效空表',
    unresolved: '待解析',
    failed: '失败',
    failed_with_reason: '失败（有原因）',
    success: '成功',
    succeeded: '成功',
    partial: '部分完成',
    completed: '已完成',
    queued: '已排队',
    running: '运行中',
    pending: '等待中',
    open: '待处理',
    resolved: '已解决',
    low: '低',
    medium: '中',
    high: '高',
    critical: '严重',
    consistent: '一致',
    slightly_diverging: '轻微偏离',
    likely_exposure_changed: '可能已调整持仓',
    insufficient_data: '数据不足',
    not_applicable: '不适用',
  }
  return labels[normalized] ?? (value ? String(value) : '状态未知')
}
