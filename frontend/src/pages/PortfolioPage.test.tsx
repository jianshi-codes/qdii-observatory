import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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
  afterEach(cleanup)

  it('shows currency-separated valuation, dividends, recurring investment, and fees', async () => {
    let portfolioRequests = 0
    let refreshSubmitted = false
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/api/portfolio/capability')) {
        return response({
          enabled: true,
          template_url: '/templates/portfolio-import-template.xlsx',
        })
      }
      if (url.includes('/api/operations/preparation-status')) {
        return response({
          active_operation: null,
          latest_operation: refreshSubmitted ? {
            id: 41,
            operation: 'sync-daily',
            status: 'succeeded',
            fund_codes: ['123456', '654321'],
            lookback_days: 10,
            report_year: 2026,
            report_quarter: 2,
            current_stage: null,
            stage_completed: 1,
            stage_total: 1,
            run_ids: [9],
            records_written: 12,
            records_failed: 0,
            created_at: '2026-08-03T08:00:00Z',
            started_at: '2026-08-03T08:00:01Z',
            finished_at: '2026-08-03T08:00:03Z',
            error_message: null,
          } : null,
        })
      }
      if (url.includes('/api/operations/sync-daily')) {
        refreshSubmitted = true
        return response({
          id: 41,
          operation: 'sync-daily',
          status: 'queued',
          fund_codes: ['123456', '654321'],
          lookback_days: 10,
          report_year: 2026,
          report_quarter: 2,
          current_stage: null,
          stage_completed: 0,
          stage_total: 1,
          run_ids: [],
          records_written: 0,
          records_failed: 0,
          created_at: '2026-08-03T08:00:00Z',
          started_at: null,
          finished_at: null,
          error_message: null,
        })
      }
      portfolioRequests += 1
      return response({
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
      })
    })
    vi.stubGlobal('fetch', fetchMock)

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
    expect(screen.getByText(/重新加载 1 个定投计划，不推定真实成交/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /下载 XLSX 模板/ })).toHaveAttribute(
      'href',
      '/templates/portfolio-import-template.xlsx',
    )
    fireEvent.click(screen.getByRole('button', { name: '刷新净值与 1 个定投' }))
    expect(await screen.findByText(/任务 #41：成功/)).toBeInTheDocument()
    await waitFor(() => expect(portfolioRequests).toBeGreaterThanOrEqual(2))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/operations/sync-daily',
      expect.objectContaining({
        body: JSON.stringify({ fund_codes: ['123456', '654321'], lookback_days: 10 }),
      }),
    )
  })

  it('previews, confirms, and refreshes the portfolio after import', async () => {
    let portfolioRequests = 0
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/api/portfolio/capability')) {
        return response({
          enabled: true,
          template_url: '/templates/portfolio-import-template.xlsx',
        })
      }
      if (url.includes('/api/portfolio/import/preview')) {
        return response({
          file_digest: 'a'.repeat(64),
          valid: true,
          positions: [{
            source_row: 5,
            share_code: '006373',
            fund_name: '国富全球科技互联混合(QDII)人民币A',
            manager_name: '国海富兰克林基金',
            platform: '测试平台',
            snapshot_date: '2026-08-01',
            currency: 'CNY',
            market_value: '10000',
            holding_profit: '500',
            holding_return_pct: '5',
            position_action: 'ADD',
            universe_action: 'RESTORE',
            nav_action: 'KEEP',
          }],
          errors: [],
          summary: {
            position_count: 1,
            cash_flow_count: 0,
            positions_to_add: 1,
            positions_to_update: 0,
            universe_to_add: 0,
            universe_to_restore: 1,
            nav_to_sync: 0,
          },
        })
      }
      if (url.includes('/api/portfolio/import/confirm')) {
        return response({
          positions_written: 1,
          cash_flows_written: 0,
          universe_added: [],
          universe_restored: ['006373'],
          nav_synced: [],
        })
      }
      if (url.includes('/api/operations/preparation-status')) {
        return response({ active_operation: null, latest_operation: null })
      }
      if (url.endsWith('/api/portfolio')) {
        portfolioRequests += 1
        return response({
          latest_nav_date: null,
          positions: [],
          currency_summaries: [],
          converted_summary: null,
        })
      }
      return response([])
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    await screen.findByText('尚未导入本地持仓')

    const file = new File([new Uint8Array([1, 2, 3])], 'portfolio.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    Object.defineProperty(file, 'arrayBuffer', {
      value: () => Promise.resolve(new Uint8Array([1, 2, 3]).buffer),
    })
    fireEvent.change(screen.getByLabelText('选择填写后的 XLSX 文件'), {
      target: { files: [file] },
    })
    fireEvent.click(screen.getByRole('button', { name: /预览并校验/ }))

    expect(await screen.findByText('从归档恢复')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '确认导入' }))

    expect(await screen.findByText('导入完成')).toBeInTheDocument()
    await waitFor(() => expect(portfolioRequests).toBeGreaterThanOrEqual(2))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/portfolio/import/confirm',
      expect.objectContaining({
        body: expect.stringContaining(`"file_digest":"${'a'.repeat(64)}"`),
      }),
    )
  })
})
