import { describe, expect, it } from 'vitest'
import { curveRows, object, stored } from './setupLabModel'

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
})
