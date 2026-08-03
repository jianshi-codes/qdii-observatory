export type Identifier = string | number

export interface PurchaseLimitSummary {
  snapshot_date: string
  channel_type: 'DIRECT' | 'DISTRIBUTION'
  channel_key: string
  channel_name: string
  availability_state: PurchaseLimitAvailabilityState
  cap_state: PurchaseLimitCapState
  daily_limit_amount: number | string | null
  currency: string
  effective_from: string | null
  source_url: string
}

export interface FundSummary {
  id: Identifier
  canonical_name: string
  manager_name: string
  representative_code: string
  original_category?: string | null
  strategy_type?: string | null
  tech_scope?: string | null
  wrapper_type?: string | null
  equity_nav_pct?: number | string | null
  fund_investment_nav_pct?: number | string | null
  us_country_pct?: number | string | null
  korea_country_pct?: number | string | null
  japan_country_pct?: number | string | null
  hong_kong_country_pct?: number | string | null
  china_country_pct?: number | string | null
  information_technology_pct?: number | string | null
  disclosed_top10_pct?: number | string | null
  report_status?: string | null
  latest_report_status?: string | null
  latest_report_period_end?: string | null
  parse_confidence?: number | string | null
  stock_holding_count?: number
  fund_holding_count?: number
  lookthrough_status?: string
  latest_nav_date?: string | null
  latest_nav_return_pct?: number | string | null
  direct_purchase_limit?: PurchaseLimitSummary | null
  distribution_purchase_limit?: PurchaseLimitSummary | null
  is_dependency?: boolean
  is_user_selected?: boolean
  [key: string]: unknown
}

export interface FundCompanyChoice {
  company_code: string
  company_name: string
}

export interface ResearchScopeChoice {
  value: string
  label: string
}

export interface FundCatalogOptions {
  companies: FundCompanyChoice[]
  source_categories: ResearchScopeChoice[]
  research_scopes: ResearchScopeChoice[]
  source_provider: string
  source_notice: string
}

export interface PublicFundCandidate {
  fund_code: string
  fund_name: string
  manager_code: string | null
  manager_name: string | null
  category: string
  research_scope: string
  currency: string
  wrapper_type: string
  source_url: string
}

export interface FundCatalogCandidates {
  items: PublicFundCandidate[]
  categories: string[]
  total: number
  source_provider: string
}

export interface PublicFundImportResult {
  status: 'succeeded' | 'partial' | 'failed'
  imported_codes: string[]
  failures: Record<string, string>
}

export interface FundDetail extends FundSummary {
  exposure_family?: string | null
  lookthrough_coverage_pct?: number | string | null
  unresolved_fund_weight_pct?: number | string | null
  max_lookthrough_depth?: number | null
  data_as_of?: string | null
  exposure_families?: Array<{
    code: string
    display_name: string
    description?: string | null
    confidence?: number | string | null
  }>
}

export interface FundShare {
  id: Identifier
  share_code: string
  share_class?: string | null
  currency?: string | null
  is_exchange_traded?: boolean
  exchange?: string | null
  latest_nav_date?: string | null
  [key: string]: unknown
}

export interface FundReport {
  id: Identifier
  report_type?: string | null
  report_year?: number | null
  report_quarter?: number | null
  period_end?: string | null
  source_provider?: string | null
  source_page_url?: string | null
  document_url?: string | null
  parse_status?: string | null
  parse_confidence?: number | string | null
  parse_error?: string | null
  [key: string]: unknown
}

export interface ExposureItem {
  id?: Identifier
  name?: string | null
  label?: string | null
  raw_name?: string | null
  name_raw?: string | null
  normalized_name?: string | null
  name_normalized?: string | null
  country_normalized?: string | null
  industry_normalized?: string | null
  nav_pct?: number | string | null
  direct_nav_pct?: number | string | null
  lookthrough_nav_pct?: number | string | null
  exposure_scope?: string | null
  [key: string]: unknown
}

export interface SecurityHolding {
  id?: Identifier
  security_code_raw?: string | null
  security_name_zh?: string | null
  security_name_en?: string | null
  security_name_raw?: string | null
  security_name_normalized?: string | null
  market_normalized?: string | null
  country_normalized?: string | null
  fair_value_cny?: number | string | null
  nav_pct?: number | string | null
  rank?: number | null
  security_type?: string | null
  [key: string]: unknown
}

export interface FundHolding {
  id?: Identifier
  fund_code_raw?: string | null
  fund_name_raw?: string | null
  normalized_name?: string | null
  fund_name_normalized?: string | null
  resolved_fund_name?: string | null
  fair_value_cny?: number | string | null
  nav_pct?: number | string | null
  rank?: number | null
  resolved?: boolean | null
  is_unresolved?: boolean | null
  [key: string]: unknown
}

export interface NavPoint {
  nav_date: string
  unit_nav?: number | string | null
  accumulated_nav?: number | string | null
  calculated_daily_return_pct?: number | string | null
  published_daily_return_pct?: number | string | null
  market_close?: number | string | null
  premium_discount_pct?: number | string | null
  share_code?: string | null
  [key: string]: unknown
}

export type PurchaseLimitChannelType = 'DIRECT' | 'DISTRIBUTION'
export type PurchaseLimitAvailabilityState =
  | 'OPEN'
  | 'PAUSED'
  | 'UNKNOWN'
  | 'NOT_SOLD'
  | 'NOT_APPLICABLE'
export type PurchaseLimitCapState = 'LIMITED' | 'UNLIMITED' | 'UNKNOWN'

export interface PurchaseLimit {
  id: Identifier
  fund_share_id: Identifier
  share_code: string
  snapshot_date: string
  channel_type: PurchaseLimitChannelType
  channel_key: string
  channel_name: string
  business_type: 'PURCHASE' | 'RECURRING_INVESTMENT' | 'CONVERSION_IN'
  availability_state: PurchaseLimitAvailabilityState
  cap_state: PurchaseLimitCapState
  daily_limit_amount: number | string | null
  currency: string
  limit_basis: 'PER_ACCOUNT_PER_DAY' | 'UNKNOWN'
  share_scope: 'PER_SHARE' | 'ALL_SHARES_COMBINED' | 'UNKNOWN'
  effective_from: string | null
  effective_to: string | null
  source_provider: string
  source_url: string
  source_published_at: string | null
  fetched_at: string
  source_artifact_id: Identifier
  raw_payload_hash: string
  raw_text: string
  confidence: number | string | null
}

export interface PurchaseLimitCoverage {
  total_funds: number
  covered_funds: number
  total_shares: number
  covered_shares: number
  latest_snapshot_date: string | null
  availability_state_counts: Partial<Record<PurchaseLimitAvailabilityState, number>>
  cap_state_counts: Partial<Record<PurchaseLimitCapState, number>>
}

export interface PortfolioCashFlow {
  flow_type: 'DIVIDEND'
  occurred_on: string | null
  occurred_year: number
  amount: number | string
  currency: string
  note: string | null
}

export interface PortfolioRecurringPlan {
  frequency: 'DAILY'
  gross_amount: number | string
  fee_pct: number | string
  net_amount: number | string
  currency: string
}

export interface PortfolioFee {
  platform_purchase_fee_pct: number | string | null
  standard_purchase_fee_pct: number | string | null
  reference_discounted_purchase_fee_pct: number | string | null
  management_fee_pct_annual: number | string | null
  custody_fee_pct_annual: number | string | null
  sales_service_fee_pct_annual: number | string | null
  source_provider: string | null
  source_url: string | null
  snapshot_date: string | null
  has_manual_override: boolean
}

export interface PortfolioPosition {
  id: Identifier
  fund_id: Identifier
  canonical_name: string
  manager_name: string
  share_code: string
  platform: string
  currency: string
  snapshot_date: string
  reported_market_value: number | string
  reported_profit_amount: number | string
  reported_return_pct: number | string
  reported_cumulative_profit_amount: number | string | null
  anchor_nav_date: string
  anchor_unit_nav: number | string
  estimated_units: number | string
  latest_nav_date: string
  latest_unit_nav: number | string
  latest_daily_return_pct: number | string | null
  estimated_market_value: number | string
  estimated_market_value_cny: number | string | null
  estimated_profit_amount: number | string
  estimated_profit_amount_cny: number | string | null
  estimated_return_pct: number | string
  estimated_cumulative_profit_amount: number | string | null
  estimated_daily_profit_amount: number | string | null
  estimated_daily_profit_amount_cny: number | string | null
  change_since_snapshot: number | string
  cash_dividend_total: number | string
  cash_flows: PortfolioCashFlow[]
  recurring_plan: PortfolioRecurringPlan | null
  fees: PortfolioFee
  data_quality_note: string | null
}

export interface PortfolioCurrencySummary {
  currency: string
  position_count: number
  estimated_market_value: number | string
  estimated_profit_amount: number | string
  estimated_return_pct: number | string | null
  estimated_daily_profit_amount: number | string | null
  estimated_daily_return_pct: number | string | null
  recurring_gross_amount: number | string
  recurring_net_amount: number | string
  recurring_net_pct: number | string | null
}

export interface PortfolioPayload {
  latest_nav_date: string | null
  positions: PortfolioPosition[]
  currency_summaries: PortfolioCurrencySummary[]
  converted_summary: {
    currency: 'CNY'
    estimated_market_value: number | string
    estimated_profit_amount: number | string
    estimated_return_pct: number | string | null
    estimated_daily_profit_amount: number | string | null
    estimated_daily_return_pct: number | string | null
    usd_cny_rate: number | string | null
    rate_date: string | null
    source_provider: string | null
    source_url: string | null
  } | null
}

export interface FundRelation {
  id?: Identifier
  relation_type: string
  target_fund_contract_id?: Identifier | null
  target_fund_name?: string | null
  external_target_name?: string | null
  external_target_code?: string | null
  weight_nav_pct?: number | string | null
  confidence?: number | string | null
  source_text?: string | null
  [key: string]: unknown
}

export interface IngestionRun {
  id: Identifier
  run_type?: string | null
  job_type?: string | null
  provider_name?: string | null
  status?: string | null
  started_at?: string | null
  completed_at?: string | null
  finished_at?: string | null
  discovered_count?: number | null
  records_seen?: number | null
  success_count?: number | null
  records_written?: number | null
  failed_count?: number | null
  records_failed?: number | null
  error_summary?: string | null
  error_message?: string | null
  parameters?: Record<string, unknown>
  [key: string]: unknown
}

export type DataOperationName =
  | 'prepare'
  | 'sync-daily'
  | 'sync-sales-limits'
  | 'sync-reports'
  | 'parse-reports'

export interface DataOperationResult {
  id: number
  operation: DataOperationName
  status: 'queued' | 'running' | 'succeeded' | 'partial' | 'failed'
  fund_codes: string[]
  lookback_days: number
  report_year: number | null
  report_quarter: number | null
  current_stage: DataOperationName | null
  stage_completed: number
  stage_total: number
  run_ids: number[]
  records_written: number
  records_failed: number
  created_at: string
  started_at: string | null
  finished_at: string | null
  error_message: string | null
}

export interface DataPreparationStatus {
  active_operation: DataOperationName | null
  latest_operation: DataOperationResult | null
  total_funds: number
  total_shares: number
  nav_ready_funds: number
  latest_nav_date: string | null
  limit_ready_funds: number
  latest_limit_snapshot_date: string | null
  report_year: number
  report_quarter: number
  report_downloaded_funds: number
  report_parsed_funds: number
  lookthrough_ready_funds: number
}

export interface DataQualityIssue {
  id: Identifier
  issue_type?: string | null
  issue_code?: string | null
  severity?: string | null
  status?: string | null
  message?: string | null
  fund_contract_id?: Identifier | null
  representative_code?: string | null
  fund_name?: string | null
  details?: Record<string, unknown>
  source_urls?: string[]
  created_at?: string | null
  detected_at?: string | null
  [key: string]: unknown
}

export interface ProviderHealth {
  name: string
  enabled: boolean
  priority: number
  status: 'HEALTHY' | 'DEGRADED' | 'RATE_LIMITED' | 'SCHEMA_CHANGED' | 'DISABLED' | 'UNKNOWN'
}

export interface ComparePayload {
  funds?: FundSummary[]
  exposure_basis?: string
  exposures?: Record<string, unknown>[]
  holding_overlaps?: Record<string, unknown>[]
  nav_series?: Record<string, unknown>[]
  return_correlations?: Record<string, unknown>[]
  [key: string]: unknown
}
