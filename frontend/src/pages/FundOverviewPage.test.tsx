import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
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
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders explicit empty-universe guidance without demo funds', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({ items: [], total: 0 })))
    renderPage()

    expect(await screen.findByText('基金 universe 尚未导入')).toBeInTheDocument()
    expect(screen.getByText(/不会使用演示基金/)).toBeInTheDocument()
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
    expect(page.getByRole('button', { name: '香港' })).toBeInTheDocument()
    expect(page.getByRole('button', { name: '中国大陆' })).toBeInTheDocument()
    expect(page.queryByRole('link', { name: /1万元\/日/ })).not.toBeInTheDocument()
    expect(page.queryByRole('columnheader', { name: 'Q2 报告' })).not.toBeInTheDocument()

    await user.click(page.getByRole('button', { name: '美国' }))
    let rows = page.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('高美国暴露基金')).toBeInTheDocument()
    await user.click(page.getByRole('button', { name: '美国' }))
    rows = page.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('低美国暴露基金')).toBeInTheDocument()

    await user.click(page.getByRole('button', { name: '香港' }))
    rows = page.getAllByRole('row').slice(1)
    expect(within(rows[0]).getByText('低美国暴露基金')).toBeInTheDocument()

    await user.click(page.getByText('显示字段'))
    expect(page.getByRole('checkbox', { name: '香港' })).toBeChecked()
    expect(page.getByRole('checkbox', { name: '中国大陆' })).toBeChecked()
    expect(page.getByRole('checkbox', { name: '直销限额' })).not.toBeChecked()
    expect(page.getByRole('checkbox', { name: '代销限额' })).not.toBeChecked()
    expect(page.getByRole('checkbox', { name: 'Q2 报告' })).not.toBeChecked()
    await user.click(page.getByRole('checkbox', { name: '直销限额' }))
    expect(page.getByRole('link', { name: /1万元\/日/ })).toHaveAttribute('href', 'https://example.test/notice.pdf')
    await user.click(page.getByRole('checkbox', { name: '韩国' }))
    expect(page.queryByRole('button', { name: '韩国' })).not.toBeInTheDocument()
  })
})
