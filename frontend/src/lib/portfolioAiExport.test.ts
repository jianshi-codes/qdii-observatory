import { describe, expect, it } from 'vitest'
import type { PortfolioConsistencyPayload, PortfolioPayload } from '../api/types'
import {
  buildPortfolioAiContext,
  portfolioAiJson,
  portfolioChatGptPrompt,
} from './portfolioAiExport'

describe('portfolio AI export', () => {
  it('keeps financial amounts and cash-flow notes but removes platform and database identifiers', () => {
    const portfolio = {
      latest_nav_date: '2026-08-03',
      positions: [{
        id: 7,
        fund_id: 31,
        canonical_name: '测试全球基金',
        manager_name: '测试基金公司',
        representative_code: '123456',
        share_code: '123456',
        platform: '私密平台',
        currency: 'CNY',
        reported_units: '8000',
        reported_market_value: '100000',
        estimated_market_value: '101000',
        estimated_market_value_cny: '101000',
        estimated_profit_amount: '1000',
        estimated_return_pct: '1.00',
        latest_daily_return_pct: '0.50',
        latest_nav_date: '2026-08-03',
        recurring_plan: { gross_amount: '1000', fee_pct: '0.15', confirmation_lag_days: 2 },
        recurring_pending_order_count: 1,
        cash_flows: [{
          flow_type: 'DIVIDEND',
          occurred_on: '2026-07-01',
          occurred_year: 2026,
          amount: '500',
          currency: 'CNY',
          note: '现金流备注',
        }],
        fees: { management_fee_pct_annual: '1.20', custody_fee_pct_annual: '0.20' },
      }],
      currency_summaries: [{ currency: 'CNY', estimated_market_value: '101000' }],
      converted_summary: {
        currency: 'CNY',
        estimated_market_value: '101000',
        estimated_profit_amount: '1000',
        estimated_return_pct: '1.00',
        estimated_daily_profit_amount: '500',
        estimated_daily_return_pct: '0.50',
        usd_cny_rate: null,
        rate_date: null,
        source_provider: null,
        source_url: null,
      },
    } as PortfolioPayload
    const analysis = {
      data_as_of: '2026-08-03',
      market_data_fetched_at: '2026-08-04T00:00:00Z',
      analysis_start_date: '2026-07-01',
      as_of: '2026-08-03',
      portfolio_prediction: {
        predicted_return_pct: '0.8',
        lower_bound_pct: '0.2',
        upper_bound_pct: '1.4',
        analyzed_portfolio_weight_pct: '100',
      },
      funds: [{
        fund_id: 31,
        representative_code: '123456',
        fund_name: '测试全球基金',
        share_codes: ['123456'],
      }],
      country_exposure: [{ name: '美国', portfolio_exposure_pct: '60' }],
      industry_exposure: [{ name: '信息技术', portfolio_exposure_pct: '50' }],
      overlaps: [{
        left_fund_id: 31,
        left_fund_name: '测试全球基金',
        right_fund_id: 32,
        right_fund_name: '测试芯片基金',
        overlap_weight_pct: '10',
        securities: [],
      }],
      limitations: ['静态披露不代表当前持仓。'],
      sources: [{
        source_type: 'REPORT',
        provider: 'CSRC',
        url: 'https://example.test/report',
        data_date: '2026-06-30',
        fetched_at: '2026-08-01T00:00:00Z',
      }],
    } as unknown as PortfolioConsistencyPayload

    const context = buildPortfolioAiContext(portfolio, analysis, new Date('2026-08-04T00:00:00Z'))
    const json = portfolioAiJson(context)
    const prompt = portfolioChatGptPrompt(context)

    expect(context.privacy.mode).toBe('PRIVATE_FINANCIAL_DATA_WITH_IDENTIFIERS_REDACTED')
    expect(json).toContain('"estimated_market_value": "101000"')
    expect(json).toContain('"note": "现金流备注"')
    expect(json).toContain('"gross_amount": "1000"')
    expect(json).not.toContain('私密平台')
    expect(json).not.toContain('"fund_id"')
    expect(json).not.toContain('"left_fund_id"')
    expect(prompt).toContain('完整持仓 JSON')
    expect(prompt).toContain('现金流备注')
  })
})
