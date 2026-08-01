import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'

function response(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }))
}

describe('API response adapters', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps the backend exposure basis on every allocation item', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({
      fund_id: 1,
      basis: 'LOOKTHROUGH',
      items: [{ id: 3, name_normalized: '美国', nav_pct: '76.42' }],
    })))

    const items = await api.countryExposure('1', 'lookthrough')

    expect(items).toEqual([
      expect.objectContaining({ name_normalized: '美国', exposure_scope: 'LOOKTHROUGH' }),
    ])
    expect(fetch).toHaveBeenCalledWith('/api/funds/1/country-exposure?basis=lookthrough', expect.any(Object))
  })

  it('merges exchange prices with NAV by share and date without replacing NAV', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({
      fund_id: 1,
      items: [{ nav_date: '2026-07-30', share_code: '159513', unit_nav: '1.2345' }],
      exchange_prices: [{ trade_date: '2026-07-30', share_code: '159513', close: '1.2500' }],
    })))

    const points = await api.nav('1')

    expect(points).toEqual([
      expect.objectContaining({ unit_nav: '1.2345', market_close: '1.2500' }),
    ])
  })

  it('sends comparison fund IDs as repeated query parameters', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({
      funds: [],
      exposure_basis: 'LOOKTHROUGH',
      exposures: [],
      holding_overlaps: [],
      nav_series: [],
      return_correlations: [],
    })))

    await api.compare(['1', '5'])

    expect(fetch).toHaveBeenCalledWith('/api/compare?fund_ids=1&fund_ids=5', expect.any(Object))
  })

  it('requests purchase-limit snapshots with explicit share, date, and channel filters', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({
      fund_id: 1,
      items: [{
        id: 9,
        share_code: '000834',
        channel_type: 'DISTRIBUTION',
        channel_key: 'EASTMONEY_TIANTIAN',
      }],
    })))

    const items = await api.purchaseLimits('1', {
      shareCode: '000834',
      snapshotDate: '2026-08-01',
      channelType: 'DISTRIBUTION',
    })

    expect(items).toEqual([
      expect.objectContaining({ channel_key: 'EASTMONEY_TIANTIAN' }),
    ])
    expect(fetch).toHaveBeenCalledWith(
      '/api/funds/1/purchase-limits?share_code=000834&snapshot_date=2026-08-01&channel_type=DISTRIBUTION',
      expect.any(Object),
    )
  })

  it('loads the latest daily purchase-limit coverage summary', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({
      total_funds: 51,
      covered_funds: 49,
      total_shares: 125,
      covered_shares: 120,
      latest_snapshot_date: '2026-08-01',
      availability_state_counts: { OPEN: 98, UNKNOWN: 3 },
      cap_state_counts: { LIMITED: 96, UNKNOWN: 5 },
    })))

    const coverage = await api.purchaseLimitCoverage()

    expect(coverage.covered_shares).toBe(120)
    expect(fetch).toHaveBeenCalledWith('/api/purchase-limit-coverage', expect.any(Object))
  })

  it('loads the local portfolio without collection adaptation', async () => {
    vi.stubGlobal('fetch', vi.fn(() => response({
      latest_nav_date: '2026-07-30',
      positions: [{ id: 1, share_code: '123456' }],
      currency_summaries: [],
    })))

    const portfolio = await api.portfolio()

    expect(portfolio.positions[0].share_code).toBe('123456')
    expect(fetch).toHaveBeenCalledWith('/api/portfolio', expect.any(Object))
  })
})
