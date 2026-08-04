import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DataPreparationStatus } from '../api/types'
import { currentQuarterHistory } from '../lib/operations'
import { DataOpsPage } from './DataOpsPage'

function response(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }))
}

it('calculates the current-quarter history range with a baseline buffer', () => {
  expect(currentQuarterHistory(new Date(2026, 7, 3))).toEqual({
    startDate: '2026-06-24',
    lookbackDays: 40,
  })
  expect(currentQuarterHistory(new Date(2026, 11, 31))).toEqual({
    startDate: '2026-09-24',
    lookbackDays: 98,
  })
})

function preparationStatus(totalFunds = 0): DataPreparationStatus {
  return {
    active_operation: null,
    latest_operation: null,
    latest_daily_operation: null,
    total_funds: totalFunds,
    total_shares: totalFunds,
    nav_ready_funds: 0,
    latest_nav_date: null,
    limit_ready_funds: 0,
    latest_limit_snapshot_date: null,
    report_year: 2026,
    report_quarter: 2,
    report_downloaded_funds: 0,
    report_parsed_funds: 0,
    lookthrough_ready_funds: 0,
  }
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><DataOpsPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DataOpsPage purchase-limit coverage', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('shows latest-day coverage, every state category, and limit quality issues', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      if (path === '/api/funds') return response({ items: [
        { id: 1, canonical_name: '基金一', manager_name: '公司一', representative_code: '000001', parse_confidence: '0.9100', stock_holding_count: 10, fund_holding_count: 2, lookthrough_status: 'partial' },
        { id: 2, canonical_name: '基金二', manager_name: '公司二', representative_code: '000002', parse_confidence: '0.7800', stock_holding_count: 8, fund_holding_count: 0, lookthrough_status: 'direct_only' },
      ] })
      if (path === '/api/ingestion-runs') return response({ items: [] })
      if (path === '/api/data-quality-issues') return response({ items: [{
        id: 8,
        issue_code: 'SALES_LIMIT_COVERAGE_INCOMPLETE',
        severity: 'high',
        status: 'open',
        message: '两只份额缺少今日渠道快照',
        fund_contract_id: 1,
        representative_code: '000001',
        fund_name: '基金一',
        source_urls: ['https://example.test/limit-source'],
      }] })
      if (path === '/api/purchase-limit-coverage') return response({
        total_funds: 2,
        covered_funds: 1,
        total_shares: 3,
        covered_shares: 2,
        latest_snapshot_date: '2026-08-01',
        availability_state_counts: { OPEN: 2, PAUSED: 1, UNKNOWN: 1, NOT_SOLD: 1, NOT_APPLICABLE: 0 },
        cap_state_counts: { LIMITED: 2, UNLIMITED: 1, UNKNOWN: 2 },
      })
      if (path === '/api/provider-health') return response({ items: [] })
      if (path === '/api/operations/preparation-status') return response(preparationStatus(2))
      if (path === '/api/fund-catalog/options') return response({
        companies: [],
        source_categories: [{ value: 'ALL', label: '全部来源分类' }],
        research_scopes: [{ value: 'ALL', label: '全部 QDII' }],
        source_provider: 'fixture',
        source_notice: '公开来源提示',
      })
      throw new Error(`unexpected request: ${path}`)
    }))

    renderPage()

    expect(await screen.findByRole('heading', { name: '每日直销 / 代销限额覆盖' })).toBeInTheDocument()
    expect(await screen.findByText('2 / 3')).toBeInTheDocument()
    expect(screen.getByText('基金覆盖 1 / 2')).toBeInTheDocument()
    expect(screen.getByText('可售状态未知')).toBeInTheDocument()
    expect(screen.getByText('该渠道未销售')).toBeInTheDocument()
    expect(screen.getByText('不适用')).toBeInTheDocument()
    expect(screen.getByText('91.0%')).toBeInTheDocument()
    expect(screen.getByText('部分穿透')).toBeInTheDocument()
    expect(screen.getByText('仅直接持仓')).toBeInTheDocument()
    expect(screen.getByText('有限额')).toBeInTheDocument()
    expect(screen.getByText('不限额')).toBeInTheDocument()
    expect(screen.getByText('限额未知')).toBeInTheDocument()
    const coverageButtons = screen.getAllByRole('button', { name: '补齐数据' })
    expect(coverageButtons).toHaveLength(2)
    for (const button of coverageButtons) {
      expect(button).not.toHaveAttribute('title')
      expect(document.getElementById(button.getAttribute('aria-describedby') ?? '')).toHaveTextContent('当前季度首日')
    }
    expect(screen.getByText('渠道覆盖不完整')).toBeInTheDocument()
    expect(screen.getByText('SALES_LIMIT_COVERAGE_INCOMPLETE')).toBeInTheDocument()
    await user.click(screen.getByText('渠道覆盖不完整'))
    expect(screen.getByText('两只份额缺少今日渠道快照')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '来源 1' })).toHaveAttribute('href', 'https://example.test/limit-source')
  })

  it('discovers by an independent source category and imports only explicitly selected funds', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/funds') return response({ items: [] })
      if (path === '/api/ingestion-runs') return response({ items: [] })
      if (path === '/api/data-quality-issues') return response({ items: [] })
      if (path === '/api/purchase-limit-coverage') return response({
        total_funds: 0,
        covered_funds: 0,
        total_shares: 0,
        covered_shares: 0,
        latest_snapshot_date: null,
        availability_state_counts: {},
        cap_state_counts: {},
      })
      if (path === '/api/provider-health') return response({ items: [] })
      if (path === '/api/operations/preparation-status') return response(preparationStatus())
      if (path === '/api/fund-catalog/options') return response({
        companies: [{ company_code: '80009999', company_name: '示例基金' }],
        source_categories: [
          { value: 'ALL', label: '全部来源分类' },
          { value: '311', label: '全球股票' },
        ],
        research_scopes: [
          { value: 'ALL', label: '全部 QDII' },
          { value: 'TECHNOLOGY', label: '科技 / 数字经济' },
        ],
        source_provider: 'fixture',
        source_notice: '公开来源提示',
      })
      if (path === '/api/fund-catalog/candidates?source_category=311') return response({
        items: [
          {
            fund_code: '900001',
            fund_name: '示例全球科技股票(QDII)A',
            manager_code: '80009999',
            manager_name: '示例基金',
            category: 'QDII-普通股票',
            research_scope: 'TECHNOLOGY',
            currency: 'CNY',
            wrapper_type: 'DIRECT',
            source_url: 'https://example.invalid/900001',
          },
          {
            fund_code: '900002',
            fund_name: '示例全球科技股票(QDII)C',
            manager_code: '80009999',
            manager_name: '示例基金',
            category: 'QDII-普通股票',
            research_scope: 'TECHNOLOGY',
            currency: 'CNY',
            wrapper_type: 'DIRECT',
            source_url: 'https://example.invalid/900002',
          },
        ],
        categories: ['QDII-普通股票'],
        total: 2,
        source_provider: 'fixture',
      })
      if (path === '/api/fund-catalog/import') {
        expect(init?.method).toBe('POST')
        expect(init?.body).toBe(JSON.stringify({ fund_codes: ['900001', '900002'] }))
        return response({ status: 'succeeded', imported_codes: ['900001', '900002'], failures: {} })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByText('请选择至少一个筛选条件')).toBeInTheDocument()
    await user.selectOptions(await screen.findByLabelText('来源分类'), '311')
    await user.click(await screen.findByRole('button', { name: '全选当前 2 个' }))
    expect(screen.getAllByRole('checkbox')).toHaveLength(2)
    for (const checkbox of screen.getAllByRole('checkbox')) expect(checkbox).toBeChecked()
    await user.click(screen.getByRole('button', { name: '取消全选' }))
    for (const checkbox of screen.getAllByRole('checkbox')) expect(checkbox).not.toBeChecked()
    await user.click(screen.getByRole('button', { name: '全选当前 2 个' }))
    await user.click(screen.getByRole('button', { name: '导入所选基金' }))

    expect(await screen.findByText('导入状态：成功')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/fund-catalog/import',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(screen.getByRole('link', { name: '下载 XLSX 模板' })).toHaveAttribute(
      'href',
      '/templates/universe-import-template.xlsx',
    )
  })

  it('renders provider status in a dedicated two-column health row', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      if (path === '/api/funds') return response({ items: [] })
      if (path === '/api/ingestion-runs') return response({ items: [] })
      if (path === '/api/data-quality-issues') return response({ items: [] })
      if (path === '/api/purchase-limit-coverage') return response({
        total_funds: 0,
        covered_funds: 0,
        total_shares: 0,
        covered_shares: 0,
        latest_snapshot_date: null,
        availability_state_counts: {},
        cap_state_counts: {},
      })
      if (path === '/api/provider-health') return response({ items: [{
        name: 'eastmoney_catalog',
        enabled: true,
        priority: 5,
        status: 'HEALTHY',
        last_checked_at: '2026-08-02T02:00:00Z',
        last_run_status: 'succeeded',
        records_failed: 0,
      }] })
      if (path === '/api/operations/preparation-status') return response(preparationStatus())
      if (path === '/api/fund-catalog/options') return response({
        companies: [],
        source_categories: [{ value: 'ALL', label: '全部来源分类' }],
        research_scopes: [{ value: 'ALL', label: '全部 QDII' }],
        source_provider: 'fixture',
        source_notice: '公开来源提示',
      })
      throw new Error(`unexpected request: ${path}`)
    }))

    const { container } = renderPage()

    expect(await screen.findByText('eastmoney_catalog')).toBeInTheDocument()
    expect(screen.getByText(/优先级 5/)).toBeInTheDocument()
    expect(screen.getByText('健康')).toBeInTheDocument()
    expect(screen.getByText(/最近验证.*成功/)).toBeInTheDocument()
    expect(container.querySelector('.provider-health-row')).toBeInTheDocument()
    expect(container.querySelector('.provider-health-row.run-row')).not.toBeInTheDocument()
  })

  it('keeps a persisted partial operation visible after a page refresh', async () => {
    const status = preparationStatus(12)
    status.total_shares = 33
    status.latest_operation = {
      id: 14,
      operation: 'prepare',
      status: 'partial',
      fund_codes: Array.from({ length: 12 }, (_, index) => String(index).padStart(6, '0')),
      lookback_days: 10,
      report_year: 2026,
      report_quarter: 2,
      current_stage: null,
      stage_completed: 3,
      stage_total: 3,
      run_ids: [5, 6, 7],
      records_written: 70,
      records_failed: 8,
      recurring_orders_created: 0,
      recurring_orders_settled: 0,
      recurring_executions_written: 0,
      recurring_positions_updated: 0,
      recurring_latest_nav_date: null,
      started_at: '2026-08-03T04:30:00Z',
      finished_at: '2026-08-03T04:42:00Z',
      error_message: null,
      created_at: '2026-08-03T04:30:00Z',
    }
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      if (path === '/api/funds') return response({ items: [] })
      if (path === '/api/ingestion-runs') return response({ items: [] })
      if (path === '/api/data-quality-issues') return response({ items: [] })
      if (path === '/api/purchase-limit-coverage') return response({
        total_funds: 12,
        covered_funds: 12,
        total_shares: 33,
        covered_shares: 33,
        latest_snapshot_date: '2026-08-03',
        availability_state_counts: {},
        cap_state_counts: {},
      })
      if (path === '/api/provider-health') return response({ items: [] })
      if (path === '/api/operations/preparation-status') return response(status)
      if (path === '/api/fund-catalog/options') return response({
        companies: [],
        source_categories: [{ value: 'ALL', label: '全部来源分类' }],
        research_scopes: [{ value: 'ALL', label: '全部 QDII' }],
        source_provider: 'fixture',
        source_notice: '公开来源提示',
      })
      throw new Error(`unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByText('任务 #14 已结束：部分完成')).toBeInTheDocument()
    expect(screen.getByText(/部分完成表示已有可用数据/)).toBeInTheDocument()
    expect(screen.getByText(/12 个基金合同、33 个份额/)).toBeInTheDocument()
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === '/api/funds')).toHaveLength(2)
    })
  })

  it('guides the user from imported funds into an explicit preparation workflow', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/funds') return response({ items: [{
        id: 1,
        canonical_name: '示例全球科技基金',
        manager_name: '示例基金',
        representative_code: '900001',
      }] })
      if (path === '/api/ingestion-runs') return response({ items: [] })
      if (path === '/api/data-quality-issues') return response({ items: [] })
      if (path === '/api/purchase-limit-coverage') return response({
        total_funds: 1,
        covered_funds: 0,
        total_shares: 1,
        covered_shares: 0,
        latest_snapshot_date: null,
        availability_state_counts: {},
        cap_state_counts: {},
      })
      if (path === '/api/provider-health') return response({ items: [] })
      if (path === '/api/operations/preparation-status') return response(preparationStatus(1))
      if (path === '/api/fund-catalog/options') return response({
        companies: [],
        source_categories: [{ value: 'ALL', label: '全部来源分类' }],
        research_scopes: [{ value: 'ALL', label: '全部 QDII' }],
        source_provider: 'fixture',
        source_notice: '公开来源提示',
      })
      if (path === '/api/operations/prepare') {
        expect(init?.method).toBe('POST')
        expect(init?.body).toBe(JSON.stringify({
          fund_codes: ['900001'],
          lookback_days: currentQuarterHistory().lookbackDays,
          force: true,
        }))
        return response({
          id: 9,
          operation: 'prepare',
          status: 'queued',
          fund_codes: ['900001'],
          lookback_days: currentQuarterHistory().lookbackDays,
          report_year: 2026,
          report_quarter: 2,
          current_stage: null,
          stage_completed: 0,
          stage_total: 3,
          run_ids: [],
          records_written: 0,
          records_failed: 0,
          created_at: '2026-08-03T01:00:00Z',
          started_at: null,
          finished_at: null,
          error_message: null,
        })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    expect(await screen.findByRole('heading', { name: '数据准备向导' })).toBeInTheDocument()
    expect(screen.getByText('净值与价格')).toBeInTheDocument()
    expect(screen.getByText('穿透计算')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '解析报告并计算穿透' })).toBeDisabled()
    const dailyButton = screen.getByRole('button', { name: '同步近 10 天每日数据' })
    const limitButton = screen.getByRole('button', { name: '仅刷新今日限额' })
    const quarterButton = screen.getByRole('button', { name: '同步本季度数据' })
    const reportButton = screen.getByRole('button', { name: '下载 2026 Q2 报告' })
    expect(document.getElementById(dailyButton.getAttribute('aria-describedby') ?? '')).toHaveTextContent('全部基金近 10 个日历日')
    expect(document.getElementById(limitButton.getAttribute('aria-describedby') ?? '')).toHaveTextContent('直销和代销')
    expect(document.getElementById(quarterButton.getAttribute('aria-describedby') ?? '')).toHaveTextContent(
      currentQuarterHistory().startDate.replaceAll('-', '/'),
    )
    expect(document.getElementById(reportButton.getAttribute('aria-describedby') ?? '')).toHaveTextContent('不会解析持仓')
    expect(screen.getByRole('button', { name: '解析报告并计算穿透' }).closest('.preparation-action-help')).toHaveAttribute('tabindex', '0')
    expect(screen.getAllByRole('option', { name: '近 5 个日历日' })).toHaveLength(2)

    await user.selectOptions(screen.getByRole('combobox', { name: '选择要补齐的基金' }), '900001')
    await user.click(screen.getByRole('button', { name: '按本季度补齐全部阶段' }))

    expect(await screen.findByText(/任务 #9：已排队/)).toBeInTheDocument()
    expect(screen.getByText(/阶段 0 \/ 3/)).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/operations/prepare',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('submits a forced manual retry even when a newer unrelated task exists', async () => {
    const user = userEvent.setup()
    const status = preparationStatus(1)
    status.latest_operation = {
      id: 12,
      operation: 'sync-daily',
      status: 'succeeded',
      fund_codes: ['160644'],
      lookback_days: 30,
      report_year: 2026,
      report_quarter: 2,
      current_stage: null,
      stage_completed: 1,
      stage_total: 1,
      run_ids: [52],
      records_written: 22,
      records_failed: 0,
      recurring_orders_created: 0,
      recurring_orders_settled: 0,
      recurring_executions_written: 0,
      recurring_positions_updated: 0,
      recurring_latest_nav_date: null,
      created_at: '2026-08-03T13:56:00Z',
      started_at: '2026-08-03T13:56:00Z',
      finished_at: '2026-08-03T13:56:10Z',
      error_message: null,
    }
    const retry = {
      ...status.latest_operation,
      id: 14,
      status: 'queued',
      fund_codes: ['002891'],
      records_written: 0,
      run_ids: [],
      created_at: '2026-08-03T14:45:26Z',
      started_at: null,
      finished_at: null,
    }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/funds') return response({ items: [{
        id: 34,
        canonical_name: '华夏移动互联混合人民币',
        manager_name: '华夏基金',
        representative_code: '002891',
      }] })
      if (path === '/api/ingestion-runs') return response({ items: [] })
      if (path === '/api/data-quality-issues') return response({ items: [] })
      if (path === '/api/purchase-limit-coverage') return response({
        total_funds: 1,
        covered_funds: 1,
        total_shares: 1,
        covered_shares: 1,
        latest_snapshot_date: '2026-08-03',
        availability_state_counts: {},
        cap_state_counts: {},
      })
      if (path === '/api/provider-health') return response({ items: [] })
      if (path === '/api/operations/preparation-status') return response(status)
      if (path === '/api/fund-catalog/options') return response({
        companies: [],
        source_categories: [{ value: 'ALL', label: '全部来源分类' }],
        research_scopes: [{ value: 'ALL', label: '全部 QDII' }],
        source_provider: 'fixture',
        source_notice: '公开来源提示',
      })
      if (path === '/api/operations/sync-daily') {
        expect(init?.body).toBe(JSON.stringify({ fund_codes: ['002891'], lookback_days: 30, force: true }))
        return response(retry)
      }
      throw new Error(`unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    await user.selectOptions(
      await screen.findByRole('combobox', { name: '选择要补齐的基金' }),
      '002891',
    )
    await user.selectOptions(
      screen.getByRole('combobox', { name: '选择日常数据回看范围' }),
      '30',
    )
    await user.click(screen.getByRole('button', { name: '补历史净值' }))

    expect(await screen.findByText(/任务 #14：已排队/)).toBeInTheDocument()
  })

  it('archives a covered fund and refreshes preparation and coverage counts', async () => {
    let archived = false
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      const activeCount = archived ? 0 : 1
      if (path === '/api/funds') return response({ items: archived ? [] : [{
        id: 1,
        canonical_name: '待归档基金',
        manager_name: '示例基金',
        representative_code: '900001',
      }] })
      if (path === '/api/ingestion-runs') return response({ items: [] })
      if (path === '/api/data-quality-issues') return response({ items: [] })
      if (path === '/api/purchase-limit-coverage') return response({
        total_funds: activeCount,
        covered_funds: activeCount,
        total_shares: activeCount,
        covered_shares: activeCount,
        latest_snapshot_date: activeCount ? '2026-08-03' : null,
        availability_state_counts: {},
        cap_state_counts: {},
      })
      if (path === '/api/provider-health') return response({ items: [] })
      if (path === '/api/operations/preparation-status') return response(preparationStatus(activeCount))
      if (path === '/api/fund-catalog/options') return response({
        companies: [],
        source_categories: [{ value: 'ALL', label: '全部来源分类' }],
        research_scopes: [{ value: 'ALL', label: '全部 QDII' }],
        source_provider: 'fixture',
        source_notice: '公开来源提示',
      })
      if (path === '/api/funds/1/archive') {
        expect(init?.method).toBe('POST')
        archived = true
        return response({ id: 1, representative_code: '900001', is_user_selected: false })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: '归档 待归档基金' }))

    expect(await screen.findByText('当前 universe 没有活跃基金')).toBeInTheDocument()
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === '/api/operations/preparation-status')).toHaveLength(2)
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === '/api/purchase-limit-coverage')).toHaveLength(2)
    })
  })
})
