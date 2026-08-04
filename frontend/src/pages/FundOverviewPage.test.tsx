import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FundOverviewPage } from './FundOverviewPage'

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <FundOverviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

describe('FundOverviewPage', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders explicit empty-universe guidance without demo funds', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({ items: [], total: 0 })))
    renderPage()

    expect(await screen.findByText('当前 universe 没有活跃基金')).toBeInTheDocument()
    expect(screen.getByText(/重新导入已归档基金会恢复原有历史数据/)).toBeInTheDocument()
  })

  it('archives a fund and refreshes the active universe immediately', async () => {
    let archived = false
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path === '/api/funds') {
        return response(archived
          ? { items: [], total: 0 }
          : { items: [{ id: 1, canonical_name: '待归档基金', manager_name: '示例基金', representative_code: '900001' }], total: 1 })
      }
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

    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('历史净值、报告和限额不会删除'))
    expect(await screen.findByText('当前 universe 没有活跃基金')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/funds/1/archive', expect.objectContaining({ method: 'POST' }))
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === '/api/funds')).toHaveLength(2)
  })

  it('renders API funds and enforces the five-fund comparison limit', async () => {
    const funds = Array.from({ length: 6 }, (_, index) => ({
      id: index + 1,
      canonical_name: `真实基金 ${index + 1}`,
      manager_name: '测试基金公司',
      representative_code: String(index + 1).padStart(6, '0'),
      original_category: '全球半导体/芯片',
      tech_scope: 'GLOBAL_SEMICONDUCTOR',
      latest_report_status: 'parsed',
      latest_nav_date: '2026-07-30',
      metrics: { equity_nav_pct: '87.50' },
    }))
    vi.stubGlobal('fetch', vi.fn(() => response({ items: funds, total: funds.length })))
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText('真实基金 1')).toBeInTheDocument()
    const selectors = funds.map((fund) => screen.getByRole('button', { name: `选择 ${fund.canonical_name}` }))
    for (const selector of selectors.slice(0, 5)) await user.click(selector)

    expect(screen.getByText('已达到 5 只对比上限；取消一只后可重新选择。')).toBeInTheDocument()
    expect(selectors[5]).toBeDisabled()
  })

  it('highlights portfolio funds and filters by holding, research domain, and tech scope', async () => {
    const funds = [
      {
        id: 1,
        canonical_name: '持仓主动科技基金',
        manager_name: '测试基金公司',
        representative_code: '000001',
        original_category: 'QDII-普通股票',
        research_scope: 'TECHNOLOGY',
        strategy_type: '全球主动股票',
        tech_scope: 'GLOBAL_ACTIVE_TECH_HIGH',
        is_portfolio_held: true,
      },
      {
        id: 2,
        canonical_name: '非持仓科技指数基金',
        manager_name: '测试基金公司',
        representative_code: '000002',
        original_category: 'QDII-指数股票',
        research_scope: 'TECHNOLOGY',
        strategy_type: '被动指数',
        tech_scope: 'NASDAQ_TECH_PURE',
        is_portfolio_held: false,
      },
      {
        id: 3,
        canonical_name: '商品基金',
        manager_name: '另一基金公司',
        representative_code: '000003',
        original_category: 'QDII-商品',
        research_scope: 'COMMODITY',
        strategy_type: '商品',
        tech_scope: 'UNKNOWN',
        is_portfolio_held: false,
      },
    ]
    vi.stubGlobal('fetch', vi.fn(() => response({ items: funds, total: funds.length })))
    const user = userEvent.setup()
    renderPage()

    const heldName = await screen.findByText('持仓主动科技基金')
    expect(heldName.closest('tr')).toHaveClass('is-portfolio-held')
    expect(within(heldName.closest('tr') as HTMLTableRowElement).getByText('持仓')).toBeInTheDocument()

    await user.selectOptions(screen.getByRole('combobox', { name: '按持仓状态筛选' }), 'HELD')
    expect(screen.getByText('持仓主动科技基金')).toBeInTheDocument()
    expect(screen.queryByText('非持仓科技指数基金')).not.toBeInTheDocument()

    await user.selectOptions(screen.getByRole('combobox', { name: '按持仓状态筛选' }), 'ALL')
    await user.selectOptions(screen.getByRole('combobox', { name: '按研究领域筛选' }), 'TECHNOLOGY')
    expect(screen.getByText('持仓主动科技基金')).toBeInTheDocument()
    expect(screen.getByText('非持仓科技指数基金')).toBeInTheDocument()
    expect(screen.queryByText('商品基金')).not.toBeInTheDocument()

    await user.selectOptions(screen.getByRole('combobox', { name: '按科技细分口径筛选' }), 'GLOBAL_ACTIVE_ALL')
    expect(screen.getByText('持仓主动科技基金')).toBeInTheDocument()
    expect(screen.queryByText('非持仓科技指数基金')).not.toBeInTheDocument()
  })

  it('shows a recoverable API error state', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('connection refused'))))
    renderPage()

    expect(await screen.findByText('这部分数据暂时不可用')).toBeInTheDocument()
    expect(screen.getByText(/确认后端服务已启动/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新请求' })).toBeInTheDocument()
  })

  it('sorts percentage and limit columns and lets the user hide fields', async () => {
    const funds = [
      {
        id: 1,
        canonical_name: '低美国暴露基金',
        manager_name: '测试基金公司',
        representative_code: '000001',
        us_country_pct: '10',
        korea_country_pct: '20',
        japan_country_pct: '30',
        hong_kong_country_pct: '60',
        china_country_pct: '40',
        latest_nav_return_pct: '-0.50',
        direct_purchase_limit: {
          snapshot_date: '2026-08-01',
          channel_type: 'DIRECT',
          channel_key: 'DIRECT',
          channel_name: '基金管理人直销',
          availability_state: 'OPEN',
          cap_state: 'LIMITED',
          daily_limit_amount: '10000',
          currency: 'CNY',
          effective_from: '2026-04-13',
          source_url: 'https://example.test/notice.pdf',
        },
      },
      {
        id: 2,
        canonical_name: '高美国暴露基金',
        manager_name: '测试基金公司',
        representative_code: '000002',
        us_country_pct: '80',
        korea_country_pct: '5',
        japan_country_pct: '2',
        hong_kong_country_pct: '3',
        china_country_pct: '1',
        latest_nav_return_pct: '1.25',
      },
    ]
    vi.stubGlobal('fetch', vi.fn(() => response({ items: funds, total: funds.length })))
    const user = userEvent.setup()
    const view = renderPage()
    const page = within(view.container)

    await page.findByText('低美国暴露基金')
    expect(page.getByText('+1.25%')).toBeInTheDocument()
    expect(page.getByRole('button', { name: '中国香港' })).toBeInTheDocument()
    expect(page.getByRole('button', { name: '中国内地' })).toBeInTheDocument()
    expect(page.queryByRole('button', { name: '信息技术' })).not.toBeInTheDocument()
    expect(page.getByRole('columnheader', { name: '最新预估涨幅' })).toBeInTheDocument()
    expect(page.queryByRole('link', { name: /1万元\/日/ })).not.toBeInTheDocument()
    expect(page.queryByRole('columnheader', { name: 'Q2 报告' })).not.toBeInTheDocument()

    await user.click(page.getByRole('button', { name: '美国' }))
    let rows = page.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('高美国暴露基金')).toBeInTheDocument()
    await user.click(page.getByRole('button', { name: '美国' }))
    rows = page.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('低美国暴露基金')).toBeInTheDocument()

    await user.click(page.getByRole('button', { name: '中国香港' }))
    rows = page.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('低美国暴露基金')).toBeInTheDocument()

    await user.click(page.getByText('显示字段'))
    expect(page.getByRole('checkbox', { name: '中国香港' })).toBeChecked()
    expect(page.getByRole('checkbox', { name: '中国内地' })).toBeChecked()
    expect(page.getByRole('checkbox', { name: '信息技术' })).not.toBeChecked()
    expect(page.getByRole('checkbox', { name: '最新预估涨幅' })).toBeChecked()
    expect(page.getByRole('checkbox', { name: '直销限额' })).not.toBeChecked()
    expect(page.getByRole('checkbox', { name: '代销限额' })).not.toBeChecked()
    expect(page.getByRole('checkbox', { name: 'Q2 报告' })).not.toBeChecked()
    await user.click(page.getByRole('checkbox', { name: '直销限额' }))
    expect(page.getByRole('link', { name: /1万元\/日/ })).toHaveAttribute('href', 'https://example.test/notice.pdf')
    await user.click(page.getByRole('checkbox', { name: '韩国' }))
    expect(page.queryByRole('button', { name: '韩国' })).not.toBeInTheDocument()
  })

  it('loads the disclosed-holdings estimate only for the requested active fund', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      if (path === '/api/funds') return response({ items: [{
        id: 1,
        canonical_name: '主动科技基金',
        manager_name: '测试基金公司',
        representative_code: '000001',
        wrapper_type: 'DIRECT',
      }], total: 1 })
      if (path === '/api/funds/1/today-estimate?share_code=000001') return response({
        share_code: '000001',
        prediction: {
          estimate_date: '2026-08-03',
          nav_date: '2026-07-31',
          predicted_return_pct: '0.80',
        },
        latest_comparison: {
          comparison_date: '2026-07-31',
          nav_date: '2026-07-30',
          predicted_return_pct: '0.70',
          actual_return_pct: '0.95',
          actual_minus_predicted_pct: '0.25',
          analysis_mode: 'Q2_LIVE',
        },
        consistency: { status: 'CONSISTENT' },
      })
      throw new Error(`unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    renderPage()

    const loadButton = await screen.findByRole('button', {
      name: '加载 主动科技基金 代表份额 000001 的 Q2 估算',
    })
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes('/today-estimate'))).toHaveLength(0)
    await user.click(loadButton)

    expect(await screen.findByText('+0.80%')).toBeInTheDocument()
    expect(screen.getByText('收益日 2026/08/03 · 对应净值日 2026/07/31')).toBeInTheDocument()
    expect(screen.getByText('+0.95%')).toBeInTheDocument()
    expect(screen.getByText('+0.25 个百分点')).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes('/today-estimate'))).toHaveLength(1)
  })
})
