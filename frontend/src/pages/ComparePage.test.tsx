import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ComparePage } from './ComparePage'

function response(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }))
}

describe('ComparePage channel guidance', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('links users to archived limit snapshots without claiming the API lacks channel data', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      if (String(input) === '/api/funds') return response({ items: [
        { id: 1, canonical_name: '基金一', manager_name: '公司一', representative_code: '000001' },
        { id: 2, canonical_name: '基金二', manager_name: '公司二', representative_code: '000002' },
      ] })
      return response({
        funds: [],
        exposure_basis: 'LOOKTHROUGH',
        exposures: [],
        holding_overlaps: [],
        nav_series: [],
        return_correlations: [],
      })
    }))
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/compare?ids=1,2']}><ComparePage /></MemoryRouter>
      </QueryClientProvider>,
    )

    expect(await screen.findByRole('heading', { name: 'Wrapper / 渠道限额入口' })).toBeInTheDocument()
    expect(screen.getAllByText(/每日限额已按份额、渠道和来源归档/)).toHaveLength(2)
    expect(screen.queryByText(/当前 API 未提供费用或申购渠道信息/)).not.toBeInTheDocument()
  })
})
