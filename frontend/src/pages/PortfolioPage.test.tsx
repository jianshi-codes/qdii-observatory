import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
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
    const today = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    }).format(new Date())
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/api/portfolio/capability')) {
        return response({
          enabled: true,
          template_url: '/templates/portfolio-import-template.xlsx',
        })
      }
      if (url.includes('/api/operations/preparation-status')) {
        const completedOperation = refreshSubmitted ? {
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
          recurring_orders_created: 1,
          recurring_orders_settled: 0,
          recurring_executions_written: 1,
          recurring_positions_updated: 1,
          recurring_latest_nav_date: '2026-07-30',
          created_at: new Date().toISOString(),
          started_at: new Date().toISOString(),
          finished_at: new Date().toISOString(),
          error_message: null,
        } : null
        return response({
          active_operation: null,
          latest_operation: completedOperation,
          latest_daily_operation: completedOperation,
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
          recurring_orders_created: 0,
          recurring_orders_settled: 0,
          recurring_executions_written: 0,
          recurring_positions_updated: 0,
          recurring_latest_nav_date: null,
          created_at: '2026-08-03T08:00:00Z',
          started_at: null,
          finished_at: null,
          error_message: null,
        })
      }
      if (url.includes('/api/portfolio/consistency')) {
        return response({
          data_as_of: '2026-08-01',
          market_data_fetched_at: '2026-08-03T08:00:00Z',
          analysis_start_date: '2026-07-01',
          as_of: '2026-08-03',
          portfolio_prediction: {
            predicted_return_pct: '0.80',
            lower_bound_pct: '0.20',
            upper_bound_pct: '1.40',
            analyzed_portfolio_weight_pct: '82.50',
          },
          funds: [{
            fund_id: 31,
            representative_code: '123456',
            fund_name: '测试全球基金',
            share_codes: ['123456'],
            report_period_end: '2026-06-30',
            report_public_available_at: '2026-07-20T00:00:00Z',
            portfolio_weight_pct: '82.50',
            prediction_date: '2026-08-03',
            prediction_nav_date: '2026-07-31',
            predicted_return_pct: '0.80',
            comparison_date: '2026-07-31',
            comparison_nav_date: '2026-07-30',
            comparison_analysis_mode: 'Q2_LIVE',
            comparison_predicted_return_pct: '0.70',
            actual_return_pct: '0.80',
            actual_minus_predicted_pct: '0.10',
            quarter_cumulative_through_date: '2026-07-31',
            quarter_cumulative_through_nav_date: '2026-07-30',
            quarter_cumulative_actual_return_pct: '12.50',
            quarter_cumulative_predicted_return_pct: '9.80',
            quarter_cumulative_actual_minus_predicted_pct: '2.70',
            quarter_cumulative_observation_count: 21,
            status: 'CONSISTENT',
            coverage_pct: '65.00',
          }],
          country_exposure: [{ name: '美国', portfolio_exposure_pct: '58.00' }],
          industry_exposure: [{ name: '信息技术', portfolio_exposure_pct: '46.00' }],
          overlaps: [],
          limitations: ['静态披露不代表当前持仓。'],
          sources: [],
        })
      }
      if (url.includes('/api/portfolio/positions/1')) {
        return response({
          positions_written: 1,
          cash_flows_written: 0,
          universe_added: [],
          universe_restored: [],
          nav_synced: [],
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
          recurring_execution_count: 1,
          recurring_invested_gross_amount: '200',
          recurring_invested_net_amount: '199.68',
          recurring_pending_order_count: refreshSubmitted ? 1 : 0,
          recurring_pending_gross_amount: refreshSubmitted ? '200' : '0',
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
          recurring_execution_count: 0,
          recurring_invested_gross_amount: '0',
          recurring_invested_net_amount: '0',
          recurring_pending_order_count: 0,
          recurring_pending_gross_amount: '0',
        },
      ],
      positions: [{
        id: 1,
        fund_id: 31,
        canonical_name: '测试全球基金',
        manager_name: '测试基金公司',
        representative_code: '123456',
        share_code: '123456',
        platform: '测试平台',
        currency: 'CNY',
        snapshot_date: '2026-08-01',
        reported_units: '7974.48',
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
          frequency: 'DAILY', gross_amount: '200', fee_pct: '0.16', net_amount: '199.68', currency: 'CNY', confirmation_lag_days: 2,
        },
        recurring_execution_count: 1,
        recurring_invested_gross_amount: '200',
        recurring_invested_net_amount: '199.68',
        last_recurring_nav_date: '2026-07-30',
        recurring_pending_order_count: refreshSubmitted ? 1 : 0,
        recurring_pending_gross_amount: refreshSubmitted ? '200' : '0',
        latest_recurring_order: refreshSubmitted ? {
          status: 'PENDING',
          order_date: today,
          expected_confirmation_date: today,
          gross_amount: '200',
          net_amount: '199.68',
          settled_nav_date: null,
          confirmed_at: null,
        } : null,
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
        representative_code: '654321',
        share_code: '654321',
        platform: '测试平台',
        currency: 'USD',
        reported_units: '5730.88',
        reported_market_value: '1629.63',
        estimated_units: '5730.88',
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
        recurring_execution_count: 0,
        recurring_invested_gross_amount: '0',
        recurring_invested_net_amount: '0',
        last_recurring_nav_date: null,
        recurring_pending_order_count: 0,
        recurring_pending_gross_amount: '0',
        latest_recurring_order: null,
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
    expect(screen.getAllByText('净值日 2026/07/30')).toHaveLength(4)
    expect(screen.getByText(/到账 99.84%/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '参考市值' }))
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('测试美元基金')
    fireEvent.click(screen.getByRole('button', { name: /参考市值/ }))
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('测试全球基金')
    expect(screen.getByText(/订单先等待申购日净值/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /下载 XLSX 模板/ })).toHaveAttribute(
      'href',
      '/templates/portfolio-import-template.xlsx',
    )
    fireEvent.click(screen.getByRole('button', { name: '刷新并触发今日定投（1 个）' }))
    expect(await screen.findByText(/任务 #41：成功.*今日下单 1 笔.*确认 0 笔/)).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: '今日已刷新' })).toBeDisabled()
    expect(await screen.findByText(new RegExp(`${today.replaceAll('-', '/')} 已触发`))).toBeInTheDocument()
    await waitFor(() => expect(portfolioRequests).toBeGreaterThanOrEqual(2))
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/operations/sync-daily',
      expect.objectContaining({
        body: JSON.stringify({ fund_codes: ['123456', '654321'], lookback_days: 10 }),
      }),
    )

    fireEvent.click(screen.getByRole('button', { name: '运行持仓一致性分析' }))
    expect(await screen.findByText('2026 Q2')).toBeInTheDocument()
    expect(screen.getByText('偏差 +2.70 个百分点')).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole('button', { name: '修正' })[0])
    expect(screen.getByRole('dialog', { name: '修正持仓快照' })).toBeInTheDocument()
    expect(screen.getByLabelText('持有份额（主数据）')).toHaveValue(7974.48)
    expect(screen.getByLabelText('平台快照市值（参考）')).toHaveValue(10000)
    expect(screen.queryByLabelText('最新涨幅')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('平台快照市值（参考）'), { target: { value: '11000' } })
    fireEvent.click(screen.getByRole('button', { name: '保存并重新计算' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/portfolio/positions/1',
      expect.objectContaining({ body: expect.stringContaining('"market_value":"11000"') }),
    ))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
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
            units: '8000',
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
    expect(screen.getByText('8,000.00')).toBeInTheDocument()
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

  it('adds one position from the manual dialog and keeps sourced fields out of the form', async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const url = String(input)
      if (url.includes('/api/portfolio/capability')) {
        return response({ enabled: true, template_url: '/templates/portfolio-import-template.xlsx' })
      }
      if (url.includes('/api/operations/preparation-status')) {
        return response({ active_operation: null, latest_operation: null })
      }
      if (url.endsWith('/api/portfolio/positions')) {
        return response({
          positions_written: 1,
          cash_flows_written: 0,
          universe_added: ['006373'],
          universe_restored: [],
          nav_synced: ['006373'],
        })
      }
      if (url.endsWith('/api/portfolio')) {
        return response({ latest_nav_date: null, positions: [], currency_summaries: [], converted_summary: null })
      }
      return response([])
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()
    await screen.findByText('尚未导入本地持仓')
    fireEvent.click(screen.getByRole('button', { name: '手动加入持仓' }))

    expect(screen.getByRole('dialog', { name: '手动加入持仓' })).toBeInTheDocument()
    expect(screen.queryByLabelText('最新涨幅')).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('基金代码'), { target: { value: '006373' } })
    fireEvent.change(screen.getByLabelText('平台'), { target: { value: '测试平台' } })
    fireEvent.change(screen.getByLabelText('持有份额（主数据）'), { target: { value: '8000' } })
    fireEvent.change(screen.getByLabelText('平台快照市值（参考）'), { target: { value: '10000' } })
    fireEvent.change(screen.getByLabelText('快照持有收益'), { target: { value: '500' } })
    fireEvent.change(screen.getByLabelText('快照持有收益率（%）'), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: '确认加入' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/portfolio/positions',
      expect.objectContaining({ body: expect.stringContaining('"units":"8000"') }),
    ))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})
