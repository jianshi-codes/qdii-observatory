import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exportDashboardPng } from '../lib/exportDashboardPng'
import { ActiveTechRegionsPage } from './ActiveTechRegionsPage'
import { ActiveTechReturnsPage } from './ActiveTechReturnsPage'

vi.mock('../components/EChart', () => ({
  EChart: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} />,
}))
vi.mock('../lib/exportDashboardPng', () => ({
  exportDashboardPng: vi.fn(() => Promise.resolve()),
}))

function renderPage(page: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{page}</QueryClientProvider>)
}

function response(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }))
}

const returnsPayload = {
  pool: 'CORE',
  period: 'DAILY',
  as_of: '2026-08-04',
  sync_date: '2026-08-04',
  latest_official_nav_date: '2026-08-01',
  common_comparable_date: '2026-07-31',
  configured_fund_count: 18,
  fund_count: 2,
  comparable_fund_count: 1,
  missing_fund_count: 1,
  stale_fund_count: 0,
  positive_fund_count: 1,
  negative_fund_count: 0,
  average_return_pct: '1.25',
  median_return_pct: '1.25',
  items: [
    {
      fund_id: 1,
      representative_code: '002891',
      fund_name: '华夏移动互联混合',
      original_category: '全球科技/互联网',
      pool_segment: 'CORE',
      share_code: '002891',
      return_pct: '1.25',
      baseline_date: '2026-07-30',
      end_date: '2026-07-31',
      latest_official_nav_date: '2026-08-01',
      nav_lag_days: 3,
      uses_accumulated_nav: true,
      status: 'READY',
    },
    {
      fund_id: 2,
      representative_code: '005698',
      fund_name: '华夏全球科技先锋混合',
      original_category: '全球科技/互联网',
      pool_segment: 'CORE',
      share_code: '005698',
      return_pct: null,
      baseline_date: null,
      end_date: '2026-07-31',
      latest_official_nav_date: '2026-07-31',
      nav_lag_days: 4,
      uses_accumulated_nav: false,
      status: 'MISSING_BASELINE',
    },
  ],
}

const regionsPayload = {
  pool: 'CORE',
  basis: 'DIRECT',
  report_year: 2026,
  report_quarter: 2,
  period_end: '2026-06-30',
  sync_date: '2026-08-04',
  configured_fund_count: 18,
  fund_count: 2,
  covered_fund_count: 1,
  missing_fund_count: 1,
  available_quarters: [
    { year: 2026, quarter: 2, period_end: '2026-06-30' },
    { year: 2026, quarter: 1, period_end: '2026-03-31' },
  ],
  average_distribution: [
    { country: '美国', average_nav_pct: '70', covered_fund_count: 1 },
    { country: '中国香港', average_nav_pct: '20', covered_fund_count: 1 },
  ],
  funds: [{
    fund_id: 1,
    representative_code: '002891',
    fund_name: '华夏移动互联混合',
    pool_segment: 'CORE',
    report_id: 1,
    report_period_end: '2026-06-30',
    parse_confidence: '0.95',
    disclosed_country_pct: '90',
    allocations: [
      { country: '美国', nav_pct: '70' },
      { country: '中国香港', nav_pct: '20' },
    ],
  }],
  missing: [{
    fund_id: 2,
    representative_code: '005698',
    fund_name: '华夏全球科技先锋混合',
    reason: 'MISSING_REPORT',
  }],
}

describe('active technology dashboards', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders return metrics, quality status, filters, and PNG export', async () => {
    const fetchMock = vi.fn(() => response(returnsPayload))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    renderPage(<ActiveTechReturnsPage />)

    expect(await screen.findByText('主动科技 QDII 收益看板')).toBeInTheDocument()
    expect((await screen.findAllByText('+1.25%')).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('缺少区间基准')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '每日收益分布直方图' })).toBeInTheDocument()
    expect(screen.getAllByText('2026/07/31').length).toBeGreaterThanOrEqual(1)

    await user.selectOptions(screen.getByRole('combobox', { name: '基金池' }), 'BROAD')
    expect(await screen.findByRole('combobox', { name: '基金池' })).toHaveValue('BROAD')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/dashboards/active-tech/returns?pool=BROAD&period=DAILY',
      expect.any(Object),
    )

    await user.click(screen.getByRole('button', { name: '导出整页 PNG' }))
    expect(exportDashboardPng).toHaveBeenCalledWith(
      expect.any(HTMLElement),
      expect.objectContaining({ width: 1440, height: 2200 }),
    )
  })

  it('renders quarter regions, basis controls, coverage gaps, and PNG export', async () => {
    const fetchMock = vi.fn(() => response(regionsPayload))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    renderPage(<ActiveTechRegionsPage />)

    expect(await screen.findByText('主动科技 QDII 地区看板')).toBeInTheDocument()
    expect(await screen.findByText('缺少季度报告')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '基金地区构成堆叠图' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '基金池平均地区分布条形图' })).toBeInTheDocument()

    await user.selectOptions(screen.getByRole('combobox', { name: '报告季度' }), '2026-Q1')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/dashboards/active-tech/regions?pool=CORE&basis=DIRECT&year=2026&quarter=1',
      expect.any(Object),
    )

    await user.click(screen.getByRole('button', { name: '导出整页 PNG' }))
    expect(exportDashboardPng).toHaveBeenCalledWith(
      expect.any(HTMLElement),
      expect.objectContaining({ width: 1440, height: 2400 }),
    )
  })
})
