import { describe, expect, it } from 'vitest'

import type { ValidateManifest } from '../../explain/types'
import { histogramBins, nullCharts } from './nullChartModel'

const tier = (name: string, extra: Record<string, unknown> = {}) => ({
  tier: name, observed: 0.8, percentile: 0.97, p_value: 0.03, threshold: 0.95, passed: true, n_paths: 100, convention_divergence: null, flagged_low_fidelity: false, ...extra,
})
const manifest = (...rows: unknown[]): ValidateManifest => ({ nulls: rows }) as unknown as ValidateManifest
const draws = (n: number, scale = 1) => Array.from({ length: n }, (_, i) => ((i / (n - 1)) * 2 - 1) * scale)

describe('histogramBins', () => {
  it('counts every finite draw once and keeps the edges ordered', () => {
    const bins = histogramBins(draws(100), 10)
    expect(bins.counts).toHaveLength(10)
    expect(bins.counts.reduce((a, b) => a + b, 0)).toBe(100)
    expect(bins.edges).toHaveLength(11)
    expect(bins.edges[0]).toBeCloseTo(-1, 9)
    expect(bins.edges[10]).toBeCloseTo(1, 9)
  })

  it('puts the largest draw in the last bin', () => {
    const bins = histogramBins([0, 0, 1], 4)
    expect(bins.counts).toEqual([2, 0, 0, 1])
  })

  it('stretches the range to hold a marker outside the draws', () => {
    const bins = histogramBins([0, 0.1, 0.2], 4, 1.5)
    expect(bins.edges[4]).toBeCloseTo(1.5, 9)
    expect(bins.counts.reduce((a, b) => a + b, 0)).toBe(3)
  })

  it('gives identical draws a real range instead of dividing by zero', () => {
    const bins = histogramBins([0.4, 0.4, 0.4], 5)
    expect(bins.edges[5]).toBeGreaterThan(bins.edges[0])
    expect(bins.counts.reduce((a, b) => a + b, 0)).toBe(3)
  })
})

describe('null charts', () => {
  it('draws one histogram per tier with the strategy marked and the recorded share of random runs that did as well', () => {
    const result = nullCharts(manifest(tier('returns_level'), tier('full_engine', { n_paths: 64, p_value: 0.25 })), {
      tiers: [{ tier: 'returns_level', statistics: draws(100) }, { tier: 'full_engine', statistics: draws(64) }],
    })
    if (result.status !== 'ok') throw new Error('expected charts')
    expect(result.tiers.map((t) => t.tier)).toEqual(['returns_level', 'full_engine'])
    const first = result.tiers[0]
    expect(first.nDraws).toBe(100)
    expect(first.marker).toBeGreaterThan(0)
    expect(first.marker).toBeLessThanOrEqual(1)
    expect(first.heights.every((h) => h >= 0 && h <= 1)).toBe(true)
    expect(Math.max(...first.heights)).toBe(1)
    expect(first.shareAsGood).toBeCloseTo(0.03, 9)
    expect(first.title).toBe('quick version')
    expect(first.detail).toBe('100 random series')
    expect(result.tiers[1].title).toBe('real engine on random prices')
    expect(first.summary).toContain('this strategy 0.80')
    expect(first.summary).toContain('random data did as well in 3.0% of draws')
  })

  it('draws a tier even when the recorded Sharpe sits outside the draws', () => {
    const result = nullCharts(manifest(tier('returns_level', { observed: 5 })), { tiers: [{ tier: 'returns_level', statistics: draws(50) }] })
    if (result.status !== 'ok') throw new Error('expected charts')
    expect(result.tiers[0].marker).toBeCloseTo(1, 9)
    expect(result.tiers[0].heights.length).toBeGreaterThan(0)
  })

  it('reads "not recorded" when the draws file is missing, and says what is missing', () => {
    const result = nullCharts(manifest(tier('returns_level')), null)
    if (result.status !== 'not-recorded') throw new Error('expected not recorded')
    expect(result.reason).toBe('the random-price draws were not recorded for this run')
  })

  it('reads "not recorded" for no tiers, an empty draw list or non-finite draws', () => {
    expect(nullCharts({} as ValidateManifest, { tiers: [] }).status).toBe('not-recorded')
    expect(nullCharts(manifest(tier('returns_level')), { tiers: [{ tier: 'returns_level', statistics: [] }] }).status).toBe('not-recorded')
    expect(nullCharts(manifest(tier('returns_level')), { tiers: [{ tier: 'returns_level', statistics: [Number.NaN, Number.POSITIVE_INFINITY] }] }).status).toBe('not-recorded')
  })

  it('skips a tier with no usable recorded Sharpe or draws, and keeps the others', () => {
    const result = nullCharts(manifest(tier('returns_level', { observed: null }), tier('full_engine')), {
      tiers: [{ tier: 'returns_level', statistics: draws(40) }, { tier: 'full_engine', statistics: draws(40) }],
    })
    if (result.status !== 'ok') throw new Error('expected charts')
    expect(result.tiers.map((t) => t.tier)).toEqual(['full_engine'])
    expect(result.skipped).toEqual(['returns_level'])
  })

  it('ignores non-finite draws and counts only the rest', () => {
    const result = nullCharts(manifest(tier('returns_level')), { tiers: [{ tier: 'returns_level', statistics: [...draws(30), Number.NaN] }] })
    if (result.status !== 'ok') throw new Error('expected charts')
    expect(result.tiers[0].nDraws).toBe(30)
  })

  it('draws one tick per draw on a number line when a tier has fewer than 20 draws, and says it is rough', () => {
    const result = nullCharts(manifest(tier('full_engine', { n_paths: 4 })), { tiers: [{ tier: 'full_engine', statistics: [-0.4, 0.1, 0.1, 0.7] }] })
    if (result.status !== 'ok') throw new Error('expected charts')
    const t = result.tiers[0]
    expect(t.mode).toBe('strip')
    expect(t.ticks).toHaveLength(4)
    expect(t.ticks.every((p) => p >= 0 && p <= 1)).toBe(true)
    expect(t.ticks[1]).toBeCloseTo(t.ticks[2], 9)
    expect(t.heights).toEqual([])
    expect(t.roughNote).toBe('only 4 random series: a rough picture')
    expect(t.summary).toContain('only 4 random series')
  })

  it('uses a histogram from 20 draws up, with no rough-picture note', () => {
    const result = nullCharts(manifest(tier('returns_level')), { tiers: [{ tier: 'returns_level', statistics: draws(20) }] })
    if (result.status !== 'ok') throw new Error('expected charts')
    expect(result.tiers[0].mode).toBe('histogram')
    expect(result.tiers[0].ticks).toEqual([])
    expect(result.tiers[0].roughNote).toBeNull()
    const nineteen = nullCharts(manifest(tier('returns_level')), { tiers: [{ tier: 'returns_level', statistics: draws(19) }] })
    if (nineteen.status !== 'ok') throw new Error('expected charts')
    expect(nineteen.tiers[0].mode).toBe('strip')
  })
})
