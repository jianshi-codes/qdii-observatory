import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { exportDashboardPng } from '../lib/exportDashboardPng'
import { ActiveTechRegionsPage } from './ActiveTechRegionsPage'
import { ActiveTechReturnsPage } from './ActiveTechReturnsPage'

vi.mock('../components/EChart', () => ({
  EChart: ({ ariaLabel, option }: { ariaLabel: string; option: unknown }) => (
    <div role="img" aria-label={ariaLabel} data-option={JSON.stringify(option)} />
  ),
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
  fund_count: 3,
  covered_fund_count: 2,
  missing_fund_count: 1,
  available_quarters: [
    { year: 2026, quarter: 2, period_end: '2026-06-30' },
    { year: 2026, quarter: 1, period_end: '2026-03-31' },
  ],
  average_distribution: [
    { country: '美国', average_nav_pct: '75', covered_fund_count: 2 },
    { country: '日本', average_nav_pct: '5.5', covered_fund_count: 2 },
    { country: '韩国', average_nav_pct: '3', covered_fund_count: 2 },
    { country: '中国香港', average_nav_pct: '9', covered_fund_count: 2 },
    { country: '中国内地', average_nav_pct: '3', covered_fund_count: 2 },
    { country: '其他分类', average_nav_pct: '2.5', covered_fund_count: 2 },
    { country: '未披露', average_nav_pct: '2', covered_fund_count: 2 },
  ],
  funds: [
    {
      fund_id: 1,
      representative_code: '002891',
      fund_name: '华夏移动互联混合',
      pool_segment: 'CORE',
      report_id: 1,
      report_period_end: '2026-06-30',
      parse_confidence: '0.95',
      disclosed_country_pct: '97',
      allocations: [
        { country: '美国', nav_pct: '70' },
        { country: '日本', nav_pct: '5' },
        { country: '韩国', nav_pct: '5' },
        { country: '中国香港', nav_pct: '10' },
        { country: '中国内地', nav_pct: '4' },
        { country: '其他分类', nav_pct: '3' },
        { country: '未披露', nav_pct: '3' },
      ],
    },
    {
      fund_id: 3,
      representative_code: '005698',
      fund_name: '华夏全球科技先锋混合',
      pool_segment: 'CORE',
      report_id: 2,
      report_period_end: '2026-06-30',
      parse_confidence: '0.96',
      disclosed_country_pct: '99',
      allocations: [
        { country: '美国', nav_pct: '80' },
        { country: '日本', nav_pct: '6' },
        { country: '韩国', nav_pct: '1' },
        { country: '中国香港', nav_pct: '8' },
        { country: '中国内地', nav_pct: '2' },
        { country: '其他分类', nav_pct: '2' },
        { country: '未披露', nav_pct: '1' },
      ],
    },
  ],
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
    const stackedChart = screen.getByRole('img', { name: '基金地区构成堆叠图' })
    const averageChart = screen.getByRole('img', { name: '基金池平均地区分布条形图' })
    const stackedOption = JSON.parse(stackedChart.getAttribute('data-option') ?? '{}')
    const averageOption = JSON.parse(averageChart.getAttribute('data-option') ?? '{}')
    expect(stackedOption.yAxis.data).toEqual([
      '华夏全球科技先锋混合\n005698',
      '华夏移动互联混合\n002891',
    ])
    expect(stackedOption.series.map((item: { name: string }) => item.name)).toEqual([
      '美国', '日本', '韩国', '中国香港', '中国内地', '其他分类', '未披露',
    ])
    expect(stackedOption.series.map((item: { itemStyle: { color: string } }) => item.itemStyle.color)).toEqual([
      '#24364b', '#ffffff', '#171717', '#9e1b64', '#d43f3a', '#5f6872', '#d9dde2',
    ])
    expect(averageOption.yAxis.data).toEqual([
      '美国', '日本', '韩国', '中国香港', '中国内地', '其他分类', '未披露',
    ])

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
