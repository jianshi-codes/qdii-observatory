import type {
  ActiveTechPeriod,
  ActiveTechPool,
  ActiveTechRegionsPayload,
  ActiveTechReturnsPayload,
  ComparePayload,
  DataQualityIssue,
  DataOperationName,
  DataOperationResult,
  DataPreparationStatus,
  ExposureItem,
  FundDetail,
  FundCatalogCandidates,
  FundCatalogOptions,
  FundHolding,
  FundRelation,
  FundReport,
  FundShare,
  FundSummary,
  FundUniverseState,
  IngestionRun,
  NavPoint,
  PortfolioCapability,
  PortfolioImportPreview,
  PortfolioImportResult,
  PortfolioConsistencyPayload,
  PortfolioEditableInput,
  PortfolioPayload,
  PortfolioPositionCreateInput,
  PurchaseLimit,
  PurchaseLimitChannelType,
  PurchaseLimitCoverage,
  ProviderHealth,
  PublicFundCandidate,
  PublicFundImportResult,
  SecurityHolding,
  TodayEstimatePayload,
} from './types'

const configuredBase = import.meta.env.VITE_API_BASE_URL?.trim()
const API_BASE = configuredBase ? configuredBase.replace(/\/$/, '') : ''

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(
  path: string,
  signal?: AbortSignal,
  init: RequestInit = {},
): Promise<T> {
  let response: Response

  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...init.headers },
      signal,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new ApiError('无法连接本地 API，请确认后端服务已启动。', 0)
  }

  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`
    try {
      const payload = (await response.json()) as { detail?: unknown; message?: unknown }
      const serverMessage = payload.detail ?? payload.message
      if (typeof serverMessage === 'string' && serverMessage.trim()) detail = serverMessage
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    throw new ApiError(detail, response.status)
  }

  return (await response.json()) as T
}

function collection<T>(payload: unknown, keys: string[]): T[] {
  if (Array.isArray(payload)) return payload as T[]
  if (!payload || typeof payload !== 'object') return []

  const record = payload as Record<string, unknown>
  for (const key of [...keys, 'items', 'results', 'data']) {
    if (Array.isArray(record[key])) return record[key] as T[]
  }
  return []
}

function navCollection(payload: unknown): NavPoint[] {
  const navItems = collection<NavPoint>(payload, ['nav', 'points'])
  if (!payload || typeof payload !== 'object') return navItems
  const prices = collection<Record<string, unknown>>(
    (payload as Record<string, unknown>).exchange_prices,
    ['exchange_prices', 'prices'],
  )
  if (prices.length === 0) return navItems

  const unmatchedPrices = new Set(prices)
  const merged: NavPoint[] = navItems.map((point): NavPoint => {
    const match = prices.find((price) => {
      const sameDate = String(price.trade_date ?? price.nav_date ?? '') === point.nav_date
      const priceShare = price.share_code
      return sameDate && (!priceShare || !point.share_code || priceShare === point.share_code)
    })
    if (!match) return point
    unmatchedPrices.delete(match)
    return {
      ...point,
      market_close: (match.close ?? match.market_close) as NavPoint['market_close'],
      premium_discount_pct: match.premium_discount_pct as NavPoint['premium_discount_pct'],
    }
  })

  for (const price of unmatchedPrices) {
    const date = price.trade_date ?? price.nav_date
    if (typeof date === 'string') {
      merged.push({
        nav_date: date,
        share_code: typeof price.share_code === 'string' ? price.share_code : null,
        market_close: (price.close ?? price.market_close) as number | string | null,
        premium_discount_pct: price.premium_discount_pct as number | string | null,
      })
    }
  }
  return merged
}

async function requestCollection<T>(
  path: string,
  keys: string[],
  signal?: AbortSignal,
): Promise<T[]> {
  return collection<T>(await request<unknown>(path, signal), keys)
}

async function requestExposure(
  path: string,
  basis: 'direct' | 'lookthrough',
  signal?: AbortSignal,
): Promise<ExposureItem[]> {
  const payload = await request<unknown>(`${path}?basis=${basis}`, signal)
  const items = collection<ExposureItem>(payload, ['exposures'])
  const responseBasis = payload && typeof payload === 'object'
    ? (payload as Record<string, unknown>).basis
    : basis
  return items.map((item) => ({ ...item, exposure_scope: String(responseBasis ?? basis) }))
}

export const api = {
  activeTechReturns: (
    filters: { pool: ActiveTechPool; period: ActiveTechPeriod },
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams(filters)
    return request<ActiveTechReturnsPayload>(
      `/api/dashboards/active-tech/returns?${query.toString()}`,
      signal,
    )
  },
  activeTechRegions: (
    filters: {
      pool: ActiveTechPool
      basis: 'DIRECT' | 'LOOKTHROUGH'
      year?: number
      quarter?: number
    },
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams({ pool: filters.pool, basis: filters.basis })
    if (filters.year && filters.quarter) {
      query.set('year', String(filters.year))
      query.set('quarter', String(filters.quarter))
    }
    return request<ActiveTechRegionsPayload>(
      `/api/dashboards/active-tech/regions?${query.toString()}`,
      signal,
    )
  },
  portfolioCapability: (signal?: AbortSignal) =>
    request<PortfolioCapability>('/api/portfolio/capability', signal),
  portfolio: (signal?: AbortSignal) => request<PortfolioPayload>('/api/portfolio', signal),
  portfolioConsistency: (signal?: AbortSignal) =>
    request<PortfolioConsistencyPayload>('/api/portfolio/consistency', signal),
  previewPortfolioImport: (
    filename: string,
    contentBase64: string,
    signal?: AbortSignal,
  ) => request<PortfolioImportPreview>('/api/portfolio/import/preview', signal, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename, content_base64: contentBase64 }),
  }),
  confirmPortfolioImport: (
    filename: string,
    contentBase64: string,
    fileDigest: string,
    signal?: AbortSignal,
  ) => request<PortfolioImportResult>('/api/portfolio/import/confirm', signal, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename, content_base64: contentBase64, file_digest: fileDigest }),
  }),
  createPortfolioPosition: (
    payload: PortfolioPositionCreateInput,
    signal?: AbortSignal,
  ) => request<PortfolioImportResult>('/api/portfolio/positions', signal, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }),
  updatePortfolioPosition: (
    id: string,
    payload: PortfolioEditableInput,
    signal?: AbortSignal,
  ) => request<PortfolioImportResult>(
    `/api/portfolio/positions/${encodeURIComponent(id)}`,
    signal,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  ),
  funds: (signal?: AbortSignal) =>
    requestCollection<FundSummary>('/api/funds', ['funds'], signal),
  archiveFund: (id: string, signal?: AbortSignal) =>
    request<FundUniverseState>(`/api/funds/${encodeURIComponent(id)}/archive`, signal, {
      method: 'POST',
    }),
  fundTodayEstimate: (
    id: string,
    options: { shareCode?: string } = {},
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams()
    if (options.shareCode) query.set('share_code', options.shareCode)
    const suffix = query.size ? `?${query.toString()}` : ''
    return request<TodayEstimatePayload>(
      `/api/funds/${encodeURIComponent(id)}/today-estimate${suffix}`,
      signal,
    )
  },
  fund: (id: string, signal?: AbortSignal) =>
    request<FundDetail>(`/api/funds/${encodeURIComponent(id)}`, signal),
  shares: (id: string, signal?: AbortSignal) =>
    requestCollection<FundShare>(`/api/funds/${encodeURIComponent(id)}/shares`, ['shares'], signal),
  reports: (id: string, signal?: AbortSignal) =>
    requestCollection<FundReport>(`/api/funds/${encodeURIComponent(id)}/reports`, ['reports'], signal),
  countryExposure: (id: string, basis: 'direct' | 'lookthrough', signal?: AbortSignal) =>
    requestExposure(`/api/funds/${encodeURIComponent(id)}/country-exposure`, basis, signal),
  industryExposure: (id: string, basis: 'direct' | 'lookthrough', signal?: AbortSignal) =>
    requestExposure(`/api/funds/${encodeURIComponent(id)}/industry-exposure`, basis, signal),
  holdings: (id: string, signal?: AbortSignal) =>
    requestCollection<SecurityHolding>(
      `/api/funds/${encodeURIComponent(id)}/holdings`,
      ['holdings', 'security_holdings'],
      signal,
    ),
  fundHoldings: (id: string, signal?: AbortSignal) =>
    requestCollection<FundHolding>(
      `/api/funds/${encodeURIComponent(id)}/fund-holdings`,
      ['holdings', 'fund_holdings'],
      signal,
    ),
  nav: (id: string, signal?: AbortSignal) =>
    request<unknown>(`/api/funds/${encodeURIComponent(id)}/nav`, signal).then(navCollection),
  purchaseLimits: (
    id: string,
    filters: {
      shareCode?: string
      snapshotDate?: string
      channelType?: PurchaseLimitChannelType
    } = {},
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams()
    if (filters.shareCode) query.set('share_code', filters.shareCode)
    if (filters.snapshotDate) query.set('snapshot_date', filters.snapshotDate)
    if (filters.channelType) query.set('channel_type', filters.channelType)
    const suffix = query.size ? `?${query.toString()}` : ''
    return requestCollection<PurchaseLimit>(
      `/api/funds/${encodeURIComponent(id)}/purchase-limits${suffix}`,
      ['purchase_limits', 'limits'],
      signal,
    )
  },
  relations: (id: string, signal?: AbortSignal) =>
    requestCollection<FundRelation>(
      `/api/funds/${encodeURIComponent(id)}/relations`,
      ['relations'],
      signal,
    ),
  compare: (ids: string[], signal?: AbortSignal) => {
    const query = new URLSearchParams()
    ids.forEach((id) => query.append('fund_ids', id))
    return request<ComparePayload>(`/api/compare?${query.toString()}`, signal)
  },
  ingestionRuns: (signal?: AbortSignal) =>
    requestCollection<IngestionRun>('/api/ingestion-runs', ['runs', 'ingestion_runs'], signal),
  dataQualityIssues: (signal?: AbortSignal) =>
    requestCollection<DataQualityIssue>(
      '/api/data-quality-issues',
      ['issues', 'data_quality_issues'],
      signal,
    ),
  purchaseLimitCoverage: (signal?: AbortSignal) =>
    request<PurchaseLimitCoverage>('/api/purchase-limit-coverage', signal),
  providerHealth: (signal?: AbortSignal) =>
    requestCollection<ProviderHealth>('/api/provider-health', ['providers'], signal),
  dataPreparationStatus: (signal?: AbortSignal) =>
    request<DataPreparationStatus>('/api/operations/preparation-status', signal),
  runDataOperation: (
    operation: DataOperationName,
    fundCodes: string[] = [],
    lookbackDays = 10,
    force = false,
    signal?: AbortSignal,
  ) => request<DataOperationResult>(`/api/operations/${operation}`, signal, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      fund_codes: fundCodes,
      lookback_days: lookbackDays,
      ...(force ? { force: true } : {}),
    }),
  }),
  fundCatalogOptions: (signal?: AbortSignal) =>
    request<FundCatalogOptions>('/api/fund-catalog/options', signal),
  fundCatalogCandidates: (filters: {
    companyCode?: string
    sourceCategory?: string
    researchScope?: string
  }, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    if (filters.companyCode) query.set('company_code', filters.companyCode)
    if (filters.sourceCategory && filters.sourceCategory !== 'ALL') {
      query.set('source_category', filters.sourceCategory)
    }
    if (filters.researchScope && filters.researchScope !== 'ALL') {
      query.set('research_scope', filters.researchScope)
    }
    return request<FundCatalogCandidates>(`/api/fund-catalog/candidates?${query}`, signal)
  },
  lookupPublicFund: (fundCode: string, signal?: AbortSignal) =>
    request<PublicFundCandidate>(
      `/api/fund-catalog/lookup/${encodeURIComponent(fundCode)}`,
      signal,
    ),
  importPublicFunds: (fundCodes: string[], signal?: AbortSignal) =>
    request<PublicFundImportResult>('/api/fund-catalog/import', signal, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fund_codes: fundCodes }),
    }),
}
