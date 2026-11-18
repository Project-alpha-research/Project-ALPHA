import { describe, expect, it } from 'vitest'
import { curveRows, object, shown, timelineMarks, stored } from './setupLabModel'

describe('Setup Lab recorded-value projection', () => {
  it('preserves zero, negative values and missing data without estimating', () => {
    expect(stored(0)).toBe('0')
    expect(stored(-0.02)).toBe('-0.02')
    expect(stored(null)).toBe('not recorded')
    expect(stored(undefined)).toBe('not recorded')
    expect(stored(true)).toBe('Yes')
    expect(stored(false)).toBe('No')
    expect(stored({ fee_bps: 1 })).toBe('{"fee_bps":1}')
    expect(object(null)).toEqual({})
    expect(object([])).toEqual({})
    expect(object('missing')).toEqual({})
  })
  it('keeps recorded null gaps and never invents a baseline', () => {
    expect(curveRows({ mean: [0, -0.02, null], drift: [0, 0.01, null], lower: [0], upper: [0] })).toEqual([
      { bar: 0, mean: 0, drift: 0, lower: 0, upper: 0 },
      { bar: 1, mean: -0.02, drift: 0.01, lower: undefined, upper: undefined },
      { bar: 2, mean: null, drift: null, lower: undefined, upper: undefined },
    ])
    expect(curveRows({ mean: [0] })).toEqual([{ bar: 0, mean: 0, drift: null, lower: null, upper: null }])
    expect(curveRows(null)).toEqual([])
  })
  it('rounds long stored decimals for display only', () => {
    expect(shown(0.005092131202109403)).toBe('0.0051')
    expect(shown(333.0899963378906)).toBe('333.09')
    expect(shown(110730)).toBe('110730')
    expect(shown(null)).toBe('not recorded')
    expect(shown('stop')).toBe('stop')
  })
  it('places stored candidates on a timeline by their own recorded dates', () => {
    const marks = timelineMarks([
      { symbol: 'AAA', event_ts: '2020-01-02T00:00:00+00:00', status: 'accepted' },
      { symbol: 'AAA', event_ts: '2020-02-03T00:00:00+00:00', status: 'rejected', reason: 'bounce' },
      { symbol: 'AAA', event_ts: null, status: 'accepted' },
    ])
    expect(marks.map(m => [m.symbol, m.rejected, m.at])).toEqual([
      ['AAA', false, Date.parse('2020-01-02T00:00:00+00:00')],
      ['AAA', true, Date.parse('2020-02-03T00:00:00+00:00')],
    ])
  })
})
