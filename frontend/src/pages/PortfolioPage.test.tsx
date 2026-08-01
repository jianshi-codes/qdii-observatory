import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PortfolioPage } from './PortfolioPage'

function response(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }))
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><PortfolioPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('PortfolioPage', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows currency-separated valuation, dividends, recurring investment, and fees', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({
      latest_nav_date: '2026-07-30',
      currency_summaries: [
        {
          currency: 'CNY',
          position_count: 1,
          estimated_market_value: '10000.00',
          estimated_profit_amount: '500.00',
          estimated_return_pct: '5.00',
          estimated_daily_profit_amount: '50.00',
          estimated_daily_return_pct: '0.50',
          recurring_gross_amount: '200',
          recurring_net_amount: '199.68',
          recurring_net_pct: '99.84',
        },
        {
          currency: 'USD',
          position_count: 1,
          estimated_market_value: '1629.63',
          estimated_profit_amount: '-100.00',
          estimated_return_pct: '-5.00',
          estimated_daily_profit_amount: '10.00',
          estimated_daily_return_pct: '0.62',
          recurring_gross_amount: '0',
          recurring_net_amount: '0',
          recurring_net_pct: null,
        },
      ],
      positions: [{
        id: 1,
        fund_id: 31,
        canonical_name: '测试全球基金',
        manager_name: '测试基金公司',
        share_code: '123456',
        platform: '测试平台',
        currency: 'CNY',
        snapshot_date: '2026-08-01',
        reported_market_value: '10000.00',
        reported_profit_amount: '500.00',
        reported_return_pct: '5.00',
        reported_cumulative_profit_amount: '750.00',
        anchor_nav_date: '2026-07-30',
        anchor_unit_nav: '1.254',
        estimated_units: '7974.48165869',
        latest_nav_date: '2026-07-30',
        latest_unit_nav: '1.254',
        latest_daily_return_pct: '0.56',
        estimated_market_value: '10000.00',
        estimated_market_value_cny: '10000.00',
        estimated_profit_amount: '500.00',
        estimated_profit_amount_cny: '500.00',
        estimated_return_pct: '5.00',
        estimated_cumulative_profit_amount: '750.00',
        estimated_daily_profit_amount: '50.00',
        estimated_daily_profit_amount_cny: '50.00',
        change_since_snapshot: '0',
        cash_dividend_total: '600.00',
        cash_flows: [
          { flow_type: 'DIVIDEND', occurred_on: '2024-01-18', occurred_year: 2024, amount: '100.00', currency: 'CNY', note: null },
          { flow_type: 'DIVIDEND', occurred_on: null, occurred_year: 2025, amount: '200.00', currency: 'CNY', note: '日期待补' },
          { flow_type: 'DIVIDEND', occurred_on: null, occurred_year: 2026, amount: '300.00', currency: 'CNY', note: '日期待补' },
        ],
        recurring_plan: {
          frequency: 'DAILY', gross_amount: '200', fee_pct: '0.16', net_amount: '199.68', currency: 'CNY',
        },
        fees: {
          platform_purchase_fee_pct: '0.16',
          standard_purchase_fee_pct: '1.60',
          reference_discounted_purchase_fee_pct: '0.16',
          management_fee_pct_annual: '1.20',
          custody_fee_pct_annual: '0.20',
          sales_service_fee_pct_annual: null,
          source_provider: 'EASTMONEY_FUND_FEE',
          source_url: 'https://example.test/fee',
          snapshot_date: '2026-08-01',
          has_manual_override: true,
        },
        data_quality_note: '平台口径包含现金分红等历史现金流。',
      }, {
        id: 2,
        fund_id: 32,
        canonical_name: '测试美元基金',
        share_code: '654321',
        platform: '测试平台',
        currency: 'USD',
        reported_market_value: '1629.63',
        estimated_market_value: '1629.63',
        estimated_market_value_cny: '11000.00',
        latest_daily_return_pct: '1.00',
        estimated_daily_profit_amount: '10.00',
        estimated_daily_profit_amount_cny: '67.50',
        estimated_profit_amount: '-100.00',
        estimated_profit_amount_cny: '-675.00',
        estimated_return_pct: '-5.00',
        estimated_cumulative_profit_amount: null,
        cash_dividend_total: '0',
        cash_flows: [],
        recurring_plan: null,
        fees: {
          platform_purchase_fee_pct: null,
          management_fee_pct_annual: '1.20',
          custody_fee_pct_annual: '0.20',
          source_url: null,
        },
        latest_nav_date: '2026-07-30',
        data_quality_note: null,
      }],
      converted_summary: {
        currency: 'CNY',
        estimated_market_value: '21000.00',
        estimated_profit_amount: '-175.00',
        estimated_return_pct: '-0.80',
        estimated_daily_profit_amount: '117.50',
        estimated_daily_return_pct: '0.56',
        usd_cny_rate: '6.75',
        rate_date: '2026-07-31',
        source_provider: 'ECB_REFERENCE_RATE',
        source_url: 'https://example.test/fx',
      },
    })))

    renderPage()

    expect(await screen.findByText('测试全球基金')).toBeInTheDocument()
    expect(screen.getAllByText('¥10,000.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('+¥50.00')).toHaveLength(2)
    expect(screen.getByText('分红 3 笔 · ¥600.00')).toBeInTheDocument()
    expect(screen.getAllByText('管理 1.20% · 托管 0.20%')).toHaveLength(2)
    expect(screen.getByRole('link', { name: /参考来源/ })).toHaveAttribute('href', 'https://example.test/fee')
    expect(screen.getByText('¥21,000.00')).toBeInTheDocument()
    expect(screen.getAllByText('+US$10.00').length).toBeGreaterThan(0)
    expect(screen.getByText('+¥117.50')).toBeInTheDocument()
    expect(screen.getByText('-0.80%')).toBeInTheDocument()
    expect(screen.getByText(/到账 99.84%/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '参考市值' }))
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('测试美元基金')
    fireEvent.click(screen.getByRole('button', { name: /参考市值/ }))
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('测试全球基金')
    expect(screen.getByText(/不会自动记为已成交/)).toBeInTheDocument()
  })
})
