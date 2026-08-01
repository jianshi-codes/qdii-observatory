import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
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
})
