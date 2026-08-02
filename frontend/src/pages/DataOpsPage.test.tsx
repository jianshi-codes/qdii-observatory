import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DataOpsPage } from './DataOpsPage'

function response(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }))
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
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      if (path === '/api/funds') return response({ items: [
        { id: 1, canonical_name: '基金一', manager_name: '公司一', representative_code: '000001' },
        { id: 2, canonical_name: '基金二', manager_name: '公司二', representative_code: '000002' },
      ] })
      if (path === '/api/ingestion-runs') return response({ items: [] })
      if (path === '/api/data-quality-issues') return response({ items: [{
        id: 8,
        issue_code: 'SALES_LIMIT_COVERAGE_INCOMPLETE',
        severity: 'high',
        status: 'open',
        message: '两只份额缺少今日渠道快照',
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
      if (path === '/api/fund-catalog/options') return response({
        companies: [],
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
    expect(screen.getByText('有限额')).toBeInTheDocument()
    expect(screen.getByText('不限额')).toBeInTheDocument()
    expect(screen.getByText('限额未知')).toBeInTheDocument()
    expect(screen.getByText('SALES_LIMIT_COVERAGE_INCOMPLETE')).toBeInTheDocument()
    expect(screen.getByText('两只份额缺少今日渠道快照')).toBeInTheDocument()
  })

  it('discovers by company and imports only explicitly selected public funds', async () => {
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
      if (path === '/api/fund-catalog/options') return response({
        companies: [{ company_code: '80009999', company_name: '示例基金' }],
        research_scopes: [
          { value: 'ALL', label: '全部 QDII' },
          { value: 'TECHNOLOGY', label: '科技 / 数字经济' },
        ],
        source_provider: 'fixture',
        source_notice: '公开来源提示',
      })
      if (path === '/api/fund-catalog/candidates?company_code=80009999') return response({
        items: [{
          fund_code: '900001',
          fund_name: '示例全球科技股票(QDII)A',
          manager_code: '80009999',
          manager_name: '示例基金',
          category: 'QDII-普通股票',
          research_scope: 'TECHNOLOGY',
          currency: 'CNY',
          wrapper_type: 'DIRECT',
          source_url: 'https://example.invalid/900001',
        }],
        categories: ['QDII-普通股票'],
        total: 1,
        source_provider: 'fixture',
      })
      if (path === '/api/fund-catalog/import') {
        expect(init?.method).toBe('POST')
        expect(init?.body).toBe(JSON.stringify({ fund_codes: ['900001'] }))
        return response({ status: 'succeeded', imported_codes: ['900001'], failures: {} })
      }
      throw new Error(`unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    await user.selectOptions(await screen.findByLabelText('基金公司'), '80009999')
    await user.click(await screen.findByRole('checkbox', { name: /示例全球科技股票/ }))
    await user.click(screen.getByRole('button', { name: '导入所选基金' }))

    expect(await screen.findByText('导入状态：成功')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/fund-catalog/import',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
