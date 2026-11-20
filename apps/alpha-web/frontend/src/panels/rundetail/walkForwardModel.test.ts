import { describe, expect, it } from 'vitest'

import type { ValidateManifest } from '../../explain/types'
import type { PriceBar } from './checkChartModel'
import { bandLines, findOverlaps, staircaseRows, walkForwardChart } from './walkForwardModel'

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
  ({
    folds, oos_semantics: 'fixed_rule_evaluation_no_refit',
    metadata: { symbol: 'AAPL', first_ts: new Date(T0 * 1000).toISOString(), last_ts: new Date((T0 + 1200 * DAY) * 1000).toISOString() },
    ...extra,
  }) as unknown as ValidateManifest

const bars: PriceBar[] = Array.from({ length: 1201 }, (_, i) => ({ t: T0 + i * DAY, c: 100 + i / 10 }))
const ok = (m: ValidateManifest, b: PriceBar[] | null = bars, points = 240) => {
  const chart = walkForwardChart(m, b, points)
  if (chart.status !== 'ok') throw new Error('expected a chart')
  return chart
}
/** `n` folds, each with 200 days of warm-up then 100 days tested, stepping by 100 days. */
const many = (n: number) => Array.from({ length: n }, (_, i) => fold(i, i * 100, i * 100 + 200, i * 100 + 205, i * 100 + 300, i % 2 ? -1.2 : 0.8))

describe('walk-forward chart: tested bands on the price', () => {
  const folds = [fold(0, 0, 100, 105, 400, 1.5), fold(1, 100, 400, 405, 800, -0.4), fold(2, 400, 800, 805, 1200, null)]

  it('puts one band on each fold by its recorded tested dates, as fractions of the window', () => {
    const chart = ok(manifest(folds))
    expect(chart.folds).toHaveLength(3)
    expect(chart.folds[0].testX0).toBeCloseTo(105 / 1200, 9)
    expect(chart.folds[0].testX1).toBeCloseTo(400 / 1200, 9)
    expect(chart.folds[2].testX1).toBeCloseTo(1, 9)
    expect(chart.folds.map((f) => f.sharpe)).toEqual([1.5, -0.4, null])
    expect(chart.firstTestX).toBeCloseTo(105 / 1200, 9)
  })

  it('alternates two tints and prints the Sharpe text of each band', () => {
    const chart = ok(manifest(folds))
    expect(chart.folds.map((f) => f.tint)).toEqual([0, 1, 0])
    expect(chart.folds.map((f) => f.label)).toEqual(['Sharpe 1.5', 'Sharpe -0.4', 'Sharpe not recorded'])
    expect(chart.folds[0].title).toBe('fold 1: tested 2020-04-15 to 2021-02-04; out-of-sample Sharpe 1.50')
  })

  it('numbers the folds 1, 2, 3 by position', () => {
    expect(ok(manifest(folds)).folds.map((f) => f.fold)).toEqual([1, 2, 3])
  })

  it('draws each fold own warm-up segment, which ends before its own tested segment starts', () => {
    const chart = ok(manifest(folds))
    for (const f of chart.folds) expect(f.trainX1).toBeLessThanOrEqual(f.testX0)
    expect(chart.folds[1].trainX0).toBeCloseTo(100 / 1200, 9)
    expect(chart.folds[1].trainX1).toBeCloseTo(400 / 1200, 9)
  })

  it('names the warm-up by what the run recorded and writes the sentence only when nothing is re-tuned', () => {
    const fixed = ok(manifest(folds))
    expect(fixed.trainLabel).toBe('warm-up: rules fixed, nothing re-tuned')
    expect(fixed.intro).toBe('The rules never change in this test. Each block is a later stretch of price the rules had not been run on.')
    const refit = ok(manifest(folds, { oos_semantics: 'fold_by_fold_refit' }))
    expect(refit.trainLabel).toBe('rules tuned here')
    expect(refit.intro).toBeNull()
    const unknown = ok(manifest(folds, { oos_semantics: undefined }))
    expect(unknown.trainLabel).toBe('training window')
    expect(unknown.intro).toBeNull()
  })

  it('gives three price ticks and year ticks, not only the two end dates', () => {
    const chart = ok(manifest(folds))
    expect(chart.priceTicks.map((t) => t.y)).toEqual([0, 0.5, 1])
    expect(chart.priceTicks.map((t) => t.label)).toEqual(['100', '160', '220'])
    expect(chart.yearTicks.map((t) => t.label)).toEqual(['2021', '2022', '2023'])
    expect(chart.yearTicks[0].x).toBeCloseTo(366 / 1200, 6)
  })

  it('thins year ticks on a long window', () => {
    const long = Array.from({ length: 2 }, (_, i) => fold(i, i * 5000, i * 5000 + 4000, i * 5000 + 4010, i * 5000 + 5000, 1))
    const chart = ok(manifest(long), null)
    expect(chart.yearTicks.length).toBeLessThanOrEqual(8)
    expect(chart.yearTicks.length).toBeGreaterThan(1)
  })

  it('draws the price from the supplied bars only, scaled 0 to 1 and thinned', () => {
    const chart = ok(manifest(folds), bars, 50)
    expect(chart.price.length).toBeLessThanOrEqual(50)
    expect(chart.price[0].x).toBeCloseTo(0, 9)
    expect(chart.price[chart.price.length - 1].x).toBeCloseTo(1, 9)
    expect(chart.priceLow).toBeCloseTo(100, 9)
    expect(chart.priceHigh).toBeCloseTo(220, 9)
    expect(chart.priceNote).toBeNull()
  })

  it('leaves out bars after the last recorded date and bars with a bad price', () => {
    const extra: PriceBar[] = [...bars, { t: T0 + 1450 * DAY, c: 9_999 }, { t: T0 + 200.5 * DAY, c: Number.NaN }]
    const chart = ok(manifest(folds), extra)
    expect(chart.priceHigh).toBeCloseTo(220, 9)
    expect(chart.price.every((point) => Number.isFinite(point.y))).toBe(true)
  })

  it('still draws the bands and the staircase when there is no price, and says why', () => {
    for (const none of [null, []]) {
      const chart = ok(manifest(folds), none)
      expect(chart.price).toEqual([])
      expect(chart.priceNote).toBe('price not available: no stored bars for AAPL')
      expect(chart.priceTicks).toEqual([])
      expect(chart.folds).toHaveLength(3)
    }
    const nameless = ok({ ...manifest(folds), metadata: {} } as unknown as ValidateManifest, null)
    expect(nameless.priceNote).toBe('price not available: the run does not name its asset')
  })
})

describe('walk-forward chart: staircase', () => {
  it('shows every fold when there are 8 or fewer', () => {
    const chart = ok(manifest(many(8)))
    expect(chart.collapsible).toBe(false)
    const rows = staircaseRows(chart.folds, false)
    expect(rows.top).toHaveLength(8)
    expect(rows.bottom).toEqual([])
    expect(rows.hidden).toBe(0)
  })

  it('collapses more than 8 folds to the first 3 and last 2, with the total, and expands on request', () => {
    const chart = ok(manifest(many(20)))
    expect(chart.collapsible).toBe(true)
    const rows = staircaseRows(chart.folds, false)
    expect(rows.top.map((f) => f.fold)).toEqual([1, 2, 3])
    expect(rows.bottom.map((f) => f.fold)).toEqual([19, 20])
    expect(rows.hidden).toBe(15)
    expect(rows.total).toBe(20)
    const all = staircaseRows(chart.folds, true)
    expect(all.top).toHaveLength(20)
    expect(all.hidden).toBe(0)
  })

  it('keeps a band on the price for every fold, however many', () => {
    expect(ok(manifest(many(31))).folds).toHaveLength(31)
  })
})

describe('walk-forward chart: warnings, summary and missing data', () => {
  it('flags a fold whose training dates run into its own tested dates, and only that fold', () => {
    const overlapping = [fold(0, 0, 120, 105, 200, 1), fold(1, 100, 200, 205, 300, 1)]
    expect(findOverlaps(overlapping.map((row) => ({ index: row.index, trainStart: Date.parse(row.train_start_ts), trainEnd: Date.parse(row.train_end_ts), testStart: Date.parse(row.test_start_ts), testEnd: Date.parse(row.test_end_ts) })))).toEqual([
      { index: 0, from: Date.parse(overlapping[0].test_start_ts), to: Date.parse(overlapping[0].train_end_ts) },
    ])
    const chart = ok(manifest(overlapping))
    expect(chart.overlaps).toHaveLength(1)
    expect(chart.overlaps[0].fold).toBe(1)
    expect(chart.overlaps[0].x0).toBeCloseTo(105 / 300, 9)
    expect(chart.overlaps[0].x1).toBeCloseTo(120 / 300, 9)
    expect(chart.folds[0].overlap).not.toBeNull()
    expect(chart.folds[1].overlap).toBeNull()
    expect(chart.warning).toBe('tuned and tested periods overlap')
  })

  it('does not flag a training window that ends exactly where the tested window starts', () => {
    const chart = ok(manifest([fold(0, 0, 100, 100, 200, 1)]))
    expect(chart.overlaps).toEqual([])
    expect(chart.warning).toBeNull()
  })

  it('reads "not recorded" for missing, undated or unreadable folds, never an empty chart', () => {
    for (const bad of [undefined, [], [{ index: 0, n_test: 5 }]]) expect(walkForwardChart(manifest(bad as unknown[]), bars).status).toBe('not-recorded')
    const text = walkForwardChart(manifest([]), bars)
    if (text.status !== 'not-recorded') throw new Error('expected not recorded')
    expect(text.reason).toMatch(/fold dates/)
    expect(walkForwardChart(manifest([{ ...fold(0, 0, 100, 105, 200, 1), test_start_ts: 'not a date' }]), bars).status).toBe('not-recorded')
  })

  it('counts a fold it could not place and keeps the rest', () => {
    const chart = ok(manifest([fold(0, 0, 100, 105, 200, 1), { ...fold(1, 100, 200, 205, 300, 1), test_end_ts: 'x' }]))
    expect(chart.skipped).toBe(1)
    expect(chart.folds).toHaveLength(1)
  })

  it('writes a text alternative with the dates and every recorded Sharpe', () => {
    const chart = ok(manifest([fold(0, 0, 100, 105, 400, 1.5), fold(1, 100, 400, 405, 800, -0.4)]))
    expect(chart.summary).toContain('2020-01-01')
    expect(chart.summary).toContain('2 tested windows')
    expect(chart.summary).toContain('1.50')
    expect(chart.summary).toContain('-0.40')
    expect(chart.summary).toContain('warm-up: rules fixed, nothing re-tuned')
  })
})

describe('walk-forward chart: what fits in a band', () => {
  const view = (sharpe: number | null) => ok(manifest([fold(0, 0, 100, 105, 400, sharpe)])).folds[0]

  it('prints the full words in a wide band, then "Sharpe" over the number, then the number alone, then nothing', () => {
    expect(bandLines(view(-1.2), 120)).toEqual(['Sharpe -1.2'])
    expect(bandLines(view(-1.2), 48)).toEqual(['Sharpe', '-1.2'])
    expect(bandLines(view(-1.2), 28)).toEqual(['-1.2'])
    expect(bandLines(view(-1.2), 12)).toBeNull()
  })

  it('never prints a made-up number for a fold with no recorded Sharpe', () => {
    expect(bandLines(view(null), 48)).toEqual(['no', 'Sharpe'])
    expect(bandLines(view(null), 20)).toBeNull()
    expect(bandLines(view(null), 160)).toEqual(['Sharpe not recorded'])
  })
})
