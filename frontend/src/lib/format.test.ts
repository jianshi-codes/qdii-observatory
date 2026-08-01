import { describe, expect, it } from 'vitest'
import { formatConfidence, formatPercent } from './format'

describe('percentage formatting', () => {
  it('keeps NAV percentage-point values as percentage points', () => {
    expect(formatPercent('42.35')).toBe('42.4%')
  })

  it('converts backend confidence ratios to display percentages', () => {
    expect(formatConfidence('0.9900')).toBe('99.0%')
  })
})
