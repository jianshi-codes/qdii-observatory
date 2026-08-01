import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { FundDetailPage } from './FundDetailPage'

vi.mock('../components/EChart', () => ({
  EChart: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} />,
}))

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
      <MemoryRouter initialEntries={['/funds/1']}>
        <Routes><Route path="/funds/:fundId" element={<FundDetailPage />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function purchaseLimit(overrides: Record<string, unknown>) {
  return {
    id: 1,
    fund_share_id: 11,
    share_code: '000834',
    snapshot_date: '2026-08-01',
    channel_type: 'DIRECT',
    channel_key: 'DIRECT',
    channel_name: '基金管理人直销中心',
    business_type: 'PURCHASE',
    availability_state: 'OPEN',
    cap_state: 'LIMITED',
    daily_limit_amount: '100',
    currency: 'CNY',
    limit_basis: 'PER_ACCOUNT_PER_DAY',
    share_scope: 'PER_SHARE',
    effective_from: '2026-06-04',
    effective_to: null,
    source_provider: 'CSRC_EID',
    source_url: 'https://eid.csrc.gov.cn/source.pdf',
    source_published_at: '2026-06-03T08:00:00Z',
    fetched_at: '2026-08-01T01:00:00Z',
    source_artifact_id: 7,
    raw_payload_hash: 'a'.repeat(64),
    raw_text: 'source text',
    confidence: '1.0',
    ...overrides,
  }
}

describe('FundDetailPage purchase-limit panel', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps availability and cap states separate and never broadens a named distributor', async () => {
    const limits = [
      purchaseLimit({ id: 1 }),
      purchaseLimit({
        id: 2,
        channel_type: 'DISTRIBUTION',
        channel_key: 'EASTMONEY_TIANTIAN',
        channel_name: '天天基金',
      }),
      purchaseLimit({
        id: 3,
        channel_type: 'DISTRIBUTION',
        channel_key: 'ALL_DISTRIBUTORS',
        channel_name: '全部代销机构',
        availability_state: 'PAUSED',
        cap_state: 'UNKNOWN',
        daily_limit_amount: null,
      }),
      purchaseLimit({ id: 4, availability_state: 'UNKNOWN', cap_state: 'UNKNOWN', daily_limit_amount: null }),
      purchaseLimit({ id: 5, availability_state: 'NOT_SOLD', cap_state: 'UNKNOWN', daily_limit_amount: null }),
      purchaseLimit({ id: 6, availability_state: 'NOT_APPLICABLE', cap_state: 'UNLIMITED', daily_limit_amount: null }),
    ]
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      if (path === '/api/funds/1') return response({
        id: 1,
        canonical_name: '广发纳斯达克100ETF联接',
        manager_name: '广发基金',
        representative_code: '000834',
      })
      if (path.endsWith('/purchase-limits')) return response({ fund_id: 1, items: limits })
      if (path.endsWith('/country-exposure?basis=direct')) return response({ basis: 'DIRECT', items: [] })
      if (path.endsWith('/country-exposure?basis=lookthrough')) return response({ basis: 'LOOKTHROUGH', items: [] })
      if (path.endsWith('/industry-exposure?basis=direct')) return response({ basis: 'DIRECT', items: [] })
      if (path.endsWith('/industry-exposure?basis=lookthrough')) return response({ basis: 'LOOKTHROUGH', items: [] })
      if (path.endsWith('/nav')) return response({ items: [], exchange_prices: [] })
      return response([])
    }))

    renderPage()

    expect(await screen.findByRole('heading', { name: '直销 / 代销每日申购限额' })).toBeInTheDocument()
    expect(screen.getAllByText('开放')).toHaveLength(2)
    expect(screen.getByText('暂停')).toBeInTheDocument()
    expect(screen.getByText('可售状态未知')).toBeInTheDocument()
    expect(screen.getByText('该渠道未销售')).toBeInTheDocument()
    expect(screen.getByText('不适用')).toBeInTheDocument()
    expect(screen.getAllByText('有限额').length).toBeGreaterThan(0)
    expect(screen.getByText('不限额', { selector: '.limit-value' })).toBeInTheDocument()
    expect(screen.getAllByText('限额未知').length).toBeGreaterThan(0)

    const namedDistributor = screen.getByText('代销 · 天天基金').closest('article')
    expect(namedDistributor).not.toBeNull()
    expect(within(namedDistributor as HTMLElement).queryByText('全部代销')).not.toBeInTheDocument()
    expect(screen.getByText('全部代销')).toBeInTheDocument()
  })

  it('shows the latest percentage and a daily-return chart beside the NAV history', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const path = String(input)
      if (path === '/api/funds/1') return response({
        id: 1,
        canonical_name: '全球科技测试基金',
        manager_name: '测试基金',
        representative_code: '000041',
        latest_nav_date: '2026-07-31',
        latest_nav_return_pct: '1.25',
      })
      if (path.endsWith('/purchase-limits')) return response({ fund_id: 1, items: [] })
      if (path.endsWith('/country-exposure?basis=direct')) return response({ basis: 'DIRECT', items: [] })
      if (path.endsWith('/country-exposure?basis=lookthrough')) return response({ basis: 'LOOKTHROUGH', items: [] })
      if (path.endsWith('/industry-exposure?basis=direct')) return response({ basis: 'DIRECT', items: [] })
      if (path.endsWith('/industry-exposure?basis=lookthrough')) return response({ basis: 'LOOKTHROUGH', items: [] })
      if (path.endsWith('/nav')) return response({
        items: [
          { share_code: '000041', nav_date: '2026-07-30', unit_nav: '1.10', published_daily_return_pct: '-0.20' },
          { share_code: '000041', nav_date: '2026-07-31', unit_nav: '1.12', published_daily_return_pct: '1.25' },
        ],
        exchange_prices: [],
      })
      return response([])
    }))

    renderPage()

    expect(await screen.findByRole('heading', { name: '每日涨跌幅' })).toBeInTheDocument()
    expect(screen.getByText('+1.25%')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '基金每日净值涨跌幅百分比时间序列图' })).toBeInTheDocument()
  })
})
