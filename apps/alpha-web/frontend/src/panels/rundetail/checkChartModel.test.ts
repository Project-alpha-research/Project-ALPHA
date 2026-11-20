import { describe, expect, it } from 'vitest'

import type { ValidateManifest } from '../../explain/types'
import { ciChart, cpcvChart, dsrChart } from './checkChartModel'

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
    expect(chart.unitNote).toBe('Both bars are Sharpe per trading period, drawn on one scale.')
  })

  it('adds the yearly figure in brackets only when the run recorded the periods in a year', () => {
    const withFactor = { ...dsr({ sharpe: -0.013, expected_max_sharpe: 0.036 }), metadata: { periods_per_year: 252 } } as unknown as ValidateManifest
    const chart = dsrChart(withFactor)
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.bars[0].perPeriod).toBe('-0.013')
    expect(chart.bars[0].perYear).toBe(`${(-0.013 * Math.sqrt(252)).toFixed(2)}`)
    expect(chart.bars[1].perYear).toBe((0.036 * Math.sqrt(252)).toFixed(2))
    expect(chart.unitNote).toContain('252 periods in a year')
    const bare = dsrChart(dsr({ sharpe: -0.013 }))
    if (bare.status !== 'ok') throw new Error('expected a chart')
    expect(bare.bars.map((bar) => bar.perYear)).toEqual([null, null])
    for (const bad of [0, -5, Number.NaN, '252']) {
      const odd = dsrChart({ ...dsr({}), metadata: { periods_per_year: bad } } as unknown as ValidateManifest)
      if (odd.status !== 'ok') throw new Error('expected a chart')
      expect(odd.bars[0].perYear).toBeNull()
    }
  })

  it('says the deflated Sharpe is a probability, with its recorded value', () => {
    const chart = dsrChart(dsr({ dsr: 0.0374 }))
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.probabilityNote).toBe('The deflated Sharpe (0.037) is a probability from 0 to 1, not a Sharpe ratio.')
    const none = dsrChart(dsr({ dsr: null }))
    if (none.status !== 'ok') throw new Error('expected a chart')
    expect(none.probabilityNote).toBeNull()
  })

  it('draws both bars from zero on one scale: lengths follow the values, the negative one runs left', () => {
    const chart = dsrChart(dsr({ sharpe: -0.013, expected_max_sharpe: 0.036 }))
    if (chart.status !== 'ok') throw new Error('expected a chart')
    const [self, luck] = chart.bars
    expect(self.to).toBeLessThan(chart.zero)
    expect(luck.to).toBeGreaterThan(chart.zero)
    expect((chart.zero - self.to) / (luck.to - chart.zero)).toBeCloseTo(0.013 / 0.036, 9)
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

  it('names the bar as the mean plus and minus one standard deviation, never as an interval of confidence', () => {
    const chart = cpcvChart(cpcv({}))
    if (chart.status !== 'ok') throw new Error('expected a chart')
    expect(chart.barName).toBe('bar: mean ± one standard deviation')
    expect(`${chart.barName} ${chart.summary} ${chart.note}`).not.toMatch(/interval|confidence/i)
  })

  it('reads "not recorded" without a split count, a mean or a spread', () => {
    expect(cpcvChart({} as ValidateManifest).status).toBe('not-recorded')
    expect(cpcvChart(cpcv({ n_folds: 0 })).status).toBe('not-recorded')
    expect(cpcvChart(cpcv({ mean_sharpe: null })).status).toBe('not-recorded')
    expect(cpcvChart(cpcv({ std_sharpe: Number.NaN })).status).toBe('not-recorded')
    expect(cpcvChart(cpcv({ std_sharpe: -1 })).status).toBe('not-recorded')
  })
})
