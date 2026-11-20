import { describe, expect, it } from 'vitest'

import type { ValidateManifest } from '../../explain/types'
import { ciChart, cpcvChart, dsrChart, findOverlaps, walkForwardChart, type PriceBar } from './checkChartModel'

const DAY = 86_400
const T0 = Date.parse('2020-01-01T00:00:00Z') / 1000

function fold(index: number, trainStart: number, trainEnd: number, testStart: number, testEnd: number, sharpe: number | null) {
  const iso = (day: number) => new Date((T0 + day * DAY) * 1000).toISOString()
  return {
    index, train_start: 0, train_end: 0, test_start: 0, test_end: 0, n_test: testEnd - testStart, oos_return: 0.01, oos_sharpe: sharpe, oos_cagr: 0.1,
    train_start_ts: iso(trainStart), train_end_ts: iso(trainEnd), test_start_ts: iso(testStart), test_end_ts: iso(testEnd),
  }
}

const manifest = (folds: unknown[], extra: Record<string, unknown> = {}): ValidateManifest =>
  ({ folds, metadata: { first_ts: new Date(T0 * 1000).toISOString(), last_ts: new Date((T0 + 400 * DAY) * 1000).toISOString() }, oos_semantics: 'fixed_rule_evaluation_no_refit', ...extra }) as unknown as ValidateManifest

const bars: PriceBar[] = Array.from({ length: 401 }, (_, i) => ({ t: T0 + i * DAY, c: 100 + i }))

describe('walk-forward chart', () => {
  const folds = [fold(0, 0, 100, 105, 200, 1.5), fold(1, 100, 200, 205, 300, -0.4), fold(2, 200, 300, 305, 400, null)]

  it('places each tested band by its recorded dates, as fractions of the window', () => {
    const chart = walkForwardChart(manifest(folds), bars)
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.testBands).toHaveLength(3)
    expect(chart.testBands[0].x0).toBeCloseTo(105 / 400, 9)
    expect(chart.testBands[0].x1).toBeCloseTo(200 / 400, 9)
    expect(chart.testBands[2].x1).toBeCloseTo(1, 9)
    expect(chart.testBands.map((band) => band.sharpe)).toEqual([1.5, -0.4, null])
  })

  it('merges the training windows into one set of bands and names them by what the run recorded', () => {
    const chart = walkForwardChart(manifest(folds), bars)
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.trainBands).toHaveLength(1)
    expect(chart.trainBands[0].x0).toBeCloseTo(0, 9)
    expect(chart.trainBands[0].x1).toBeCloseTo(300 / 400, 9)
    expect(chart.trainLabel).toBe('warm-up window: rules fixed, nothing re-tuned')
    const refit = walkForwardChart(manifest(folds, { oos_semantics: 'fold_by_fold_refit' }), bars)
    if (refit.status !== 'ok') throw new Error('expected a chart')
    expect(refit.trainLabel).toBe('rules tuned here')
    const unknown = walkForwardChart(manifest(folds, { oos_semantics: undefined }), bars)
    if (unknown.status !== 'ok') throw new Error('expected a chart')
    expect(unknown.trainLabel).toBe('training window')
  })

  it('draws the price from the supplied bars only, scaled 0 to 1 and thinned', () => {
    const chart = walkForwardChart(manifest(folds), bars, 50)
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.price.length).toBeLessThanOrEqual(50)
    expect(chart.price[0].x).toBeCloseTo(0, 9)
    expect(chart.price[chart.price.length - 1].x).toBeCloseTo(1, 9)
    expect(chart.price[0].y).toBeCloseTo(0, 9)
    expect(chart.price[chart.price.length - 1].y).toBeCloseTo(1, 9)
    expect(chart.priceLow).toBeCloseTo(100, 9)
    expect(chart.priceHigh).toBeCloseTo(500, 9)
  })

  it('leaves out bars after the last recorded date and bars with a bad price', () => {
    const extra: PriceBar[] = [...bars, { t: T0 + 450 * DAY, c: 9_999 }, { t: T0 + 200.5 * DAY, c: Number.NaN }]
    const chart = walkForwardChart(manifest(folds), extra)
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.priceHigh).toBeCloseTo(500, 9)
    expect(chart.price.every((point) => Number.isFinite(point.y))).toBe(true)
  })

  it('still draws the bands when no price was recorded, and says the line is missing', () => {
    for (const none of [null, []]) {
      const chart = walkForwardChart(manifest(folds), none)
      if (chart.status !== 'ok') throw new Error('expected a chart')
      expect(chart.price).toEqual([])
      expect(chart.priceNote).toBe('price line not recorded for this run')
      expect(chart.testBands).toHaveLength(3)
    }
  })

  it('flags a fold whose training dates run into its own tested dates', () => {
    const overlapping = [fold(0, 0, 120, 105, 200, 1), fold(1, 100, 200, 205, 300, 1)]
    expect(findOverlaps(overlapping.map((row) => ({ index: row.index, trainStart: Date.parse(row.train_start_ts), trainEnd: Date.parse(row.train_end_ts), testStart: Date.parse(row.test_start_ts), testEnd: Date.parse(row.test_end_ts) })))).toEqual([
      { index: 0, from: Date.parse(overlapping[0].test_start_ts), to: Date.parse(overlapping[0].train_end_ts) },
    ])
    const chart = walkForwardChart(manifest(overlapping), bars)
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.overlaps).toHaveLength(1)
    expect(chart.overlaps[0].x0).toBeCloseTo(105 / 300, 9)
    expect(chart.overlaps[0].x1).toBeCloseTo(120 / 300, 9)
    expect(chart.warning).toBe('tuned and tested periods overlap')
  })

  it('does not flag a training window that ends exactly where the tested window starts', () => {
    const touching = [fold(0, 0, 100, 100, 200, 1)]
    const chart = walkForwardChart(manifest(touching), bars)
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.overlaps).toEqual([])
    expect(chart.warning).toBeNull()
  })

  it('reads "not recorded" for missing, undated or unreadable folds, never an empty chart', () => {
    for (const bad of [undefined, [], [{ index: 0, n_test: 5 }]]) {
      const chart = walkForwardChart(manifest(bad as unknown[]), bars)
      expect(chart.status).toBe('not-recorded')
    }
    const text = walkForwardChart(manifest([]), bars)
    if (text.status !== 'not-recorded') throw new Error('expected not recorded')
    expect(text.reason).toMatch(/fold dates/)
    const garbled = { ...fold(0, 0, 100, 105, 200, 1), test_start_ts: 'not a date' }
    expect(walkForwardChart(manifest([garbled]), bars).status).toBe('not-recorded')
  })

  it('counts a fold it could not place and keeps the rest', () => {
    const garbled = { ...fold(1, 100, 200, 205, 300, 1), test_end_ts: 'x' }
    const chart = walkForwardChart(manifest([fold(0, 0, 100, 105, 200, 1), garbled]), bars)
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.skipped).toBe(1)
    expect(chart.testBands).toHaveLength(1)
  })

  it('writes a text alternative with the dates and every recorded Sharpe', () => {
    const chart = walkForwardChart(manifest(folds), bars)
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.summary).toContain('2020-01-01')
    expect(chart.summary).toContain('3 tested windows')
    expect(chart.summary).toContain('1.50')
    expect(chart.summary).toContain('-0.40')
  })
})

describe('bootstrap interval chart', () => {
  const ci = (row: Record<string, unknown>): ValidateManifest => ({ cis: [{ metric: 'sharpe', confidence: 0.95, point: 0.5, lower: -0.2, upper: 1.4, ...row }] }) as unknown as ValidateManifest

  it('puts zero, the bar and the dot on one line and says whether the bar includes zero', () => {
    const chart = ciChart(ci({}))
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.includesZero).toBe(true)
    expect(chart.zero).toBeGreaterThan(chart.lower)
    expect(chart.zero).toBeLessThan(chart.upper)
    expect(chart.point).toBeGreaterThan(chart.lower)
    expect(chart.point).toBeLessThan(chart.upper)
    expect(chart.lower).toBeGreaterThanOrEqual(0)
    expect(chart.upper).toBeLessThanOrEqual(1)
    expect(chart.summary).toBe('Sharpe 0.50; 95% interval from -0.20 to 1.40; the interval includes zero.')
  })

  it('keeps zero on the line when the whole interval is above it', () => {
    const chart = ciChart(ci({ lower: 0.3, upper: 1.4 }))
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.includesZero).toBe(false)
    expect(chart.zero).toBeGreaterThanOrEqual(0)
    expect(chart.zero).toBeLessThan(chart.lower)
    expect(chart.summary).toContain('above zero')
  })

  it('reads "not recorded" for a missing, non-finite or disordered interval', () => {
    expect(ciChart({} as ValidateManifest).status).toBe('not-recorded')
    expect(ciChart(ci({ lower: null })).status).toBe('not-recorded')
    expect(ciChart(ci({ upper: Number.NaN })).status).toBe('not-recorded')
    expect(ciChart(ci({ point: null })).status).toBe('not-recorded')
    expect(ciChart(ci({ lower: 2, upper: 1 })).status).toBe('not-recorded')
  })
})

describe('deflated Sharpe chart', () => {
  const dsr = (row: Record<string, unknown>): ValidateManifest => ({ dsr: { sharpe: 0.08, psr: 0.99, dsr: 0.9, expected_max_sharpe: 0.05, n_trials: 12, threshold: 0.95, passed: false, ...row } }) as unknown as ValidateManifest

  it('draws two bars on one scale that includes zero', () => {
    const chart = dsrChart(dsr({}))
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.bars.map((bar) => bar.label)).toEqual(["this strategy's Sharpe", 'best Sharpe expected from luck across 12 counted tests'])
    expect(chart.bars[0].value).toBeCloseTo(0.08, 9)
    expect(chart.bars[1].value).toBeCloseTo(0.05, 9)
    expect(chart.bars[0].to).toBeGreaterThan(chart.bars[1].to)
    expect(chart.zero).toBeGreaterThanOrEqual(0)
    expect(chart.unitNote).toBe('Sharpe per trading period, not per year')
  })

  it('handles a negative Sharpe by putting the zero line inside the scale', () => {
    const chart = dsrChart(dsr({ sharpe: -0.03 }))
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.zero).toBeGreaterThan(0)
    expect(chart.bars[0].from).toBeCloseTo(chart.zero, 9)
    expect(chart.bars[0].to).toBeLessThan(chart.zero)
  })

  it('words the one-test case without inventing a luck level', () => {
    const chart = dsrChart(dsr({ n_trials: 1, expected_max_sharpe: 0 }))
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.bars[1].label).toBe('best Sharpe expected from luck across 1 counted test')
    expect(chart.bars[1].value).toBe(0)
  })

  it('reads "not recorded" when either input is missing or not a number', () => {
    expect(dsrChart({} as ValidateManifest).status).toBe('not-recorded')
    expect(dsrChart(dsr({ sharpe: null })).status).toBe('not-recorded')
    expect(dsrChart(dsr({ expected_max_sharpe: Number.NaN })).status).toBe('not-recorded')
    expect(dsrChart(dsr({ n_trials: 0 })).status).toBe('not-recorded')
  })
})

describe('combinatorial cross-validation chart', () => {
  const cpcv = (row: Record<string, unknown>): ValidateManifest => ({ cpcv: { n_folds: 15, mean_sharpe: 1.2, std_sharpe: 0.5, frac_positive: 0.8, passed: true, ...row } }) as unknown as ValidateManifest

  it('draws the recorded mean and spread, and says the single splits were not stored', () => {
    const chart = cpcvChart(cpcv({}))
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.mode).toBe('summary')
    expect(chart.mean).toBeGreaterThan(chart.low)
    expect(chart.mean).toBeLessThan(chart.high)
    expect(chart.zero).toBeGreaterThanOrEqual(0)
    expect(chart.zero).toBeLessThan(chart.low)
    expect(chart.note).toBe('15 splits; the Sharpe of each split is not stored, only this summary')
    expect(chart.summary).toContain('80% of splits above zero')
  })

  it('reads "not recorded" without a split count, a mean or a spread', () => {
    expect(cpcvChart({} as ValidateManifest).status).toBe('not-recorded')
    expect(cpcvChart(cpcv({ n_folds: 0 })).status).toBe('not-recorded')
    expect(cpcvChart(cpcv({ mean_sharpe: null })).status).toBe('not-recorded')
    expect(cpcvChart(cpcv({ std_sharpe: Number.NaN })).status).toBe('not-recorded')
    expect(cpcvChart(cpcv({ std_sharpe: -1 })).status).toBe('not-recorded')
  })
})
